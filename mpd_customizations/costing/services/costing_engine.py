from typing import Dict

import frappe
from frappe.utils import now_datetime

from mpd_customizations.costing.services.config import get_config
from mpd_customizations.costing.services.cost_calculator import (
	compute_additional_charge_amount,
	compute_financing_cost_for_line,
	compute_processing_cost,
	compute_rm_line_amount,
	compute_total_cost,
)
from mpd_customizations.costing.services.formulation_selector import FormulationSelector
from mpd_customizations.costing.services.rate_fetcher import RateFetcher
from mpd_customizations.costing.services.rate_source_registry import RateSourceRegistry


class CostingEngine:
	def __init__(self, registry: RateSourceRegistry, config=None):
		self._registry = registry
		self._config = config or get_config()

	def evaluate(self, costing_request_name: str, trigger: str = "manual") -> Dict:
		doc = frappe.get_doc("Costing Request", costing_request_name)

		if not doc.item:
			frappe.throw(frappe._("Product is required."))
		if not doc.processor:
			frappe.throw(frappe._("Processor is required."))
		if not doc.solids_content_pct:
			frappe.throw(frappe._("Solids Content % is required."))

		bom_exists = frappe.db.exists("BOM", {"item": doc.item})
		if not bom_exists:
			frappe.throw(frappe._("No BOM found for item {0}.").format(doc.item))

		city = frappe.db.get_value("Processor", doc.processor, "city")
		if not city:
			frappe.throw(frappe._("Processor {0} has no city configured.").format(doc.processor))

		fetch_result = RateFetcher.fetch(doc, preserve_overrides=True)
		doc.save(ignore_permissions=True)

		boms = frappe.get_all(
			"BOM",
			filters={"item": doc.item},
			fields=["name", "item", "quantity", "custom_formulation_id"],
		)

		bom_names = [b["name"] for b in boms]
		all_bom_items = frappe.get_all(
			"BOM Item",
			filters={"parent": ["in", bom_names]},
			fields=["parent", "item_code", "item_name", "qty", "uom"],
		)

		bom_items_map: Dict[str, list] = {}
		for bi in all_bom_items:
			bom_items_map.setdefault(bi["parent"], []).append(bi)

		rate_lines_map = {rl.item: rl for rl in (doc.rate_lines or [])}
		processing_line = doc.processing_lines[0] if doc.processing_lines else None

		production_days = doc.production_days or 30
		financing_rate = doc.supplier_financing_rate_pct or 12.0
		solids = doc.solids_content_pct or 0

		additional_charges_per_kg = sum(
			compute_additional_charge_amount(c.rate or 0, c.basis, solids)
			for c in (doc.additional_charges or [])
		)

		combination_results = []
		for bom in boms:
			bom_item_list = bom_items_map.get(bom["name"], [])
			bom_qty = bom["quantity"] or 1
			material_lines_data = []
			rm_cost = 0.0
			financing_cost = 0.0
			missing_items = []
			expired_items = []

			for bi in bom_item_list:
				qty_per_kg = (bi["qty"] or 0) / bom_qty
				rl = rate_lines_map.get(bi["item_code"])
				working_rate = (rl.working_rate or 0) if rl else 0.0
				credit_days = (rl.working_supplier_credit_days or 0) if rl else 0
				freshness = (rl.rate_freshness or "Missing") if rl else "Missing"
				supplier = (rl.supplier or None) if rl else None

				amount = compute_rm_line_amount(qty_per_kg, working_rate)
				fin = compute_financing_cost_for_line(amount, production_days, credit_days, financing_rate)
				net_financed = max(0, production_days - credit_days)

				rm_cost += amount
				financing_cost += fin

				if freshness == "Missing":
					missing_items.append(bi.item_code)
				elif freshness == "Expired":
					expired_items.append(bi.item_code)

				material_lines_data.append({
					"costing_request": costing_request_name,
					"item": bi["item_code"],
					"item_name": bi["item_name"],
					"uom": bi["uom"],
					"qty_per_kg_output": qty_per_kg,
					"supplier": supplier,
					"city": city,
					"rate_freshness": freshness,
					"working_rate": working_rate,
					"working_supplier_credit_days": credit_days,
					"net_financed_days": net_financed,
					"amount_per_kg": amount,
					"financing_cost_per_kg": fin,
					"confidence_score": (rl.confidence_score if rl and hasattr(rl, "confidence_score") else 50.0),
				})

			processing_cost = 0.0
			processing_charge_ref = None
			outward_freight = 0.0
			if processing_line:
				processing_cost = compute_processing_cost(solids, processing_line.working_charge_per_kg or 0)
				processing_charge_ref = processing_line.processing_charge_ref
				if not processing_line.working_includes_outward_freight:
					outward_freight = processing_line.working_freight_per_unit or 0

			total = compute_total_cost(rm_cost, financing_cost, processing_cost, additional_charges_per_kg, outward_freight)

			if missing_items:
				status = "Indicative — Rates Missing"
			elif expired_items:
				status = "Indicative — Rates Expired"
			else:
				status = "Ready to Quote"

			combination_results.append({
				"bom": bom["name"],
				"formulation_id": bom["custom_formulation_id"] or "",
				"rm_cost_per_kg": rm_cost,
				"financing_cost_per_kg": financing_cost,
				"processing_cost_per_kg": processing_cost,
				"additional_charges_per_kg": additional_charges_per_kg,
				"outward_freight_per_kg": outward_freight,
				"total_cost_per_kg": total,
				"status": status,
				"processing_charge_ref": processing_charge_ref or "",
				"missing_items": ", ".join(missing_items),
				"expired_items": ", ".join(expired_items),
				"material_lines": material_lines_data,
			})

		selector = FormulationSelector(self._config)
		selection = selector.select(combination_results, doc.preferred_bom)

		# Remember which BOM was previously selected before wiping combinations
		previously_selected_bom = None
		if doc.selected_combination:
			previously_selected_bom = frappe.db.get_value(
				"Costing Combination", doc.selected_combination, "bom"
			)

		frappe.db.delete("Costing Material Line", {"costing_request": costing_request_name})
		frappe.db.delete("Costing Combination", {"costing_request": costing_request_name})

		now = now_datetime()
		saved_combinations = []
		for combo in combination_results:
			cc = frappe.get_doc({
				"doctype": "Costing Combination",
				"costing_request": costing_request_name,
				"bom": combo["bom"],
				"formulation_id": combo["formulation_id"],
				"is_preferred": combo.get("is_preferred", 0),
				"rm_cost_per_kg": combo["rm_cost_per_kg"],
				"financing_cost_per_kg": combo["financing_cost_per_kg"],
				"processing_cost_per_kg": combo["processing_cost_per_kg"],
				"additional_charges_per_kg": combo["additional_charges_per_kg"],
				"outward_freight_per_kg": combo["outward_freight_per_kg"],
				"total_cost_per_kg": combo["total_cost_per_kg"],
				"rank": combo.get("rank") or 1,
				"delta_pct": combo.get("delta_pct", 0),
				"status": combo["status"],
				"is_selected": 0,
				"processing_charge_ref": combo["processing_charge_ref"],
				"missing_items": combo["missing_items"],
				"expired_items": combo["expired_items"],
				"evaluated_on": now,
			})
			cc.insert(ignore_permissions=True)
			combo["combination_name"] = cc.name

			for ml in combo["material_lines"]:
				ml["combination"] = cc.name
				frappe.get_doc(dict(doctype="Costing Material Line", **ml)).insert(ignore_permissions=True)

			saved_combinations.append(cc)

		# Re-select the combination for the same BOM that was previously selected
		new_selected_name = None
		new_selected_cost = None
		if previously_selected_bom:
			reselect = next((cc for cc in saved_combinations if cc.bom == previously_selected_bom), None)
			if reselect:
				new_selected_name = reselect.name
				new_selected_cost = reselect.total_cost_per_kg
				frappe.db.set_value("Costing Combination", reselect.name, "is_selected", 1)

		mode = _compute_mode(fetch_result, new_selected_name or doc.selected_combination)
		update_fields = {
			"last_evaluated_on": now,
			"engine_version_used": self._config.engine_version,
			"mode": mode,
			"formulation_switch_alert": selection.switch_alert or "",
		}
		if new_selected_name:
			update_fields["selected_combination"] = new_selected_name
			update_fields["confirmed_ex_factory_cost_per_kg"] = new_selected_cost
		else:
			update_fields["selected_combination"] = ""
			update_fields["confirmed_ex_factory_cost_per_kg"] = 0

		frappe.db.set_value("Costing Request", costing_request_name, update_fields)

		return {
			"combinations": [_combination_to_dict(cc, combination_results) for cc in saved_combinations],
			"fetch_result": {
				"has_missing_rates": fetch_result.has_missing_rates,
				"missing_items": fetch_result.missing_items,
				"has_expired_rates": fetch_result.has_expired_rates,
				"expired_items": fetch_result.expired_items,
				"overrides_detected": fetch_result.overrides_detected,
				"overrides_changed": fetch_result.overrides_changed,
			},
			"switch_alert": selection.switch_alert,
			"mode": mode,
		}


def _compute_mode(fetch_result, selected_combination) -> str:
	if fetch_result.has_missing_rates:
		return "Awaiting Rates"
	if fetch_result.has_expired_rates:
		return "Partially Costed"
	if selected_combination:
		return "Ready to Quote"
	return "Partially Costed"


def _combination_to_dict(cc, results) -> Dict:
	raw = next((r for r in results if r["bom"] == cc.bom), {})
	return {
		"name": cc.name,
		"bom": cc.bom,
		"formulation_id": cc.formulation_id,
		"rank": cc.rank,
		"delta_pct": cc.delta_pct,
		"status": cc.status,
		"is_preferred": cc.is_preferred,
		"is_selected": cc.is_selected,
		"rm_cost_per_kg": cc.rm_cost_per_kg,
		"financing_cost_per_kg": cc.financing_cost_per_kg,
		"processing_cost_per_kg": cc.processing_cost_per_kg,
		"additional_charges_per_kg": cc.additional_charges_per_kg,
		"outward_freight_per_kg": cc.outward_freight_per_kg,
		"total_cost_per_kg": cc.total_cost_per_kg,
		"material_lines": raw.get("material_lines", []),
	}

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

	def evaluate(self, pricing_calculation_name: str, trigger: str = "manual") -> Dict:
		doc = frappe.get_doc("Pricing Calculation", pricing_calculation_name)

		if not doc.item:
			frappe.throw(frappe._("Product is required."))
		if not doc.solids_content_pct:
			frappe.throw(frappe._("Solids Content % is required."))
		if not doc.city:
			frappe.throw(frappe._("City is required on the Pricing Calculation."))

		bom_exists = frappe.db.exists("BOM", {"item": doc.item})
		if not bom_exists:
			frappe.throw(frappe._("No BOM found for item {0}.").format(doc.item))

		city = doc.city

		# If processor set, optionally validate city matches
		if doc.processor:
			processor_city = frappe.db.get_value("Processor", doc.processor, "city")
			if processor_city and processor_city != city:
				frappe.throw(
					frappe._("Processor {0} is configured for city {1}, but this calculation is for city {2}.").format(
						doc.processor, processor_city, city
					)
				)

		fetch_result = RateFetcher.fetch(doc, preserve_overrides=True)
		doc.save(ignore_permissions=True)

		boms = frappe.get_all(
			"BOM",
			filters={"item": doc.item},
			fields=["name", "item", "quantity", "custom_formulation_id", "custom_formulation_description"],
		)

		bom_names = [b["name"] for b in boms]
		all_bom_items = frappe.get_all(
			"BOM Item",
			filters={"parent": ["in", bom_names]},
			fields=["parent", "item_code", "item_name", "qty", "uom"],
		)
		all_scrap_items = frappe.get_all(
			"BOM Scrap Item",
			filters={"parent": ["in", bom_names]},
			fields=["parent", "item_code", "item_name", "stock_qty", "stock_uom"],
		)

		bom_items_map: Dict[str, list] = {}
		for bi in all_bom_items:
			bom_items_map.setdefault(bi["parent"], []).append(bi)

		scrap_items_map: Dict[str, list] = {}
		for si in all_scrap_items:
			scrap_items_map.setdefault(si["parent"], []).append(si)

		# Build map of previous approved PC's RM costs per BOM for delta display
		prev_rm_costs = {}
		if doc.pricing_request:
			prev_pc_name = frappe.db.get_value("Pricing Request", doc.pricing_request, "previous_pricing_ref")
			if prev_pc_name:
				prev_combos = frappe.get_all(
					"Costing Combination",
					filters={"pricing_calculation": prev_pc_name},
					fields=["bom", "rm_cost_per_kg"],
				)
				prev_rm_costs = {c.bom: c.rm_cost_per_kg for c in prev_combos}

		rate_lines_map = {rl.item: rl for rl in (doc.rate_lines or [])}
		scrap_lines_map = {sl.item: sl for sl in (doc.scrap_lines or [])}
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
				fin = compute_financing_cost_for_line(amount, production_days, 60, financing_rate)
				net_financed = max(0, production_days - 60)

				rm_cost += amount
				financing_cost += fin

				if freshness == "Missing":
					missing_items.append(bi["item_code"])
				elif freshness == "Expired":
					expired_items.append(bi["item_code"])

				material_lines_data.append({
					"pricing_calculation": pricing_calculation_name,
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
					"equalized_amount_per_kg": amount,
					"is_scrap": 0,
					"confidence_score": (rl.confidence_score if rl and hasattr(rl, "confidence_score") else 50.0),
				})

			for si in scrap_items_map.get(bom["name"], []):
				qty_per_kg = (si["stock_qty"] or 0) / bom_qty
				sl = scrap_lines_map.get(si["item_code"])
				scrap_rate = (sl.rate_per_kg or 0) if sl else 0.0
				scrap_amount = -1 * compute_rm_line_amount(qty_per_kg, scrap_rate)
				rm_cost += scrap_amount

				material_lines_data.append({
					"pricing_calculation": pricing_calculation_name,
					"item": si["item_code"],
					"item_name": si["item_name"],
					"uom": si["stock_uom"],
					"qty_per_kg_output": qty_per_kg,
					"supplier": None,
					"city": city,
					"rate_freshness": "Current",
					"working_rate": scrap_rate,
					"working_supplier_credit_days": 0,
					"net_financed_days": 0,
					"amount_per_kg": scrap_amount,
					"financing_cost_per_kg": 0.0,
					"equalized_amount_per_kg": scrap_amount,
					"is_scrap": 1,
					"confidence_score": 0.0,
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
				"formulation_description": bom.get("custom_formulation_description") or "",
				"prev_rm_cost_per_kg": prev_rm_costs.get(bom["name"], 0) or 0,
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

		previously_selected_bom = None
		if doc.selected_combination:
			previously_selected_bom = frappe.db.get_value(
				"Costing Combination", doc.selected_combination, "bom"
			)

		frappe.db.delete("Costing Material Line", {"pricing_calculation": pricing_calculation_name})
		frappe.db.delete("Costing Combination", {"pricing_calculation": pricing_calculation_name})

		now = now_datetime()
		saved_combinations = []
		for combo in combination_results:
			cc = frappe.get_doc({
				"doctype": "Costing Combination",
				"pricing_calculation": pricing_calculation_name,
				"bom": combo["bom"],
				"formulation_id": combo["formulation_id"],
				"formulation_description": combo.get("formulation_description") or "",
				"prev_rm_cost_per_kg": combo.get("prev_rm_cost_per_kg", 0),
				"is_preferred": combo.get("is_preferred", 0),
				"rm_cost_per_kg": combo["rm_cost_per_kg"],
				"financing_cost_per_kg": combo["financing_cost_per_kg"],
				"processing_cost_per_kg": combo["processing_cost_per_kg"],
				"additional_charges_per_kg": combo["additional_charges_per_kg"],
				"outward_freight_per_kg": combo["outward_freight_per_kg"],
				"total_cost_per_kg": combo["total_cost_per_kg"],
				"rank": combo.get("rank") or 0,
				"delta_pct": combo.get("delta_pct") or 0,
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

		frappe.db.set_value("Pricing Calculation", pricing_calculation_name, update_fields)

		# Sync mode → Pricing Request status
		_sync_to_pricing_request(doc, mode, update_fields.get("confirmed_ex_factory_cost_per_kg"))

		# Create/clear draft Material Rate requests for purchase team
		_update_pending_rate_items(doc, fetch_result, mode)

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
		return "Ready for Working"
	if selected_combination:
		return "Ready to Quote"
	return "Ready for Working"


def _sync_to_pricing_request(doc, mode: str, confirmed_cost=None):
	if not doc.pricing_request:
		return
	update = {"status": mode}
	if confirmed_cost is not None:
		update["confirmed_price_per_kg"] = confirmed_cost
		qty = frappe.db.get_value("Pricing Request", doc.pricing_request, "quantity_kg") or 0
		update["total_price"] = qty * confirmed_cost
	frappe.db.set_value("Pricing Request", doc.pricing_request, update)


def _update_pending_rate_items(doc, fetch_result, mode: str):
	if not frappe.db.has_column("Material Rate", "pricing_calculation"):
		return

	# Clear old pending-request drafts for this calculation
	frappe.db.delete("Material Rate", {
		"pricing_calculation": doc.name,
		"docstatus": 0,
		"requested_on": ["is", "set"],
	})

	if mode not in ("Awaiting Rates", "Ready for Working"):
		return

	priority = "Normal"
	product = ""
	if doc.pricing_request:
		pr_values = frappe.db.get_value(
			"Pricing Request", doc.pricing_request, ["priority", "product"], as_dict=True
		) or {}
		priority = pr_values.get("priority") or "Normal"
		product = pr_values.get("product") or ""

	items_to_request = list(fetch_result.missing_items)
	items_to_request += [i for i in fetch_result.expired_items if i not in items_to_request]

	for item_code in items_to_request:
		existing = frappe.db.exists("Material Rate", {
			"item": item_code,
			"city": doc.city,
			"docstatus": 0,
		})
		if not existing:
			frappe.get_doc({
				"doctype": "Material Rate",
				"item": item_code,
				"city": doc.city,
				"pricing_calculation": doc.name,
				"pricing_request": doc.pricing_request or "",
				"product": product,
				"priority": priority,
				"requested_on": frappe.utils.now_datetime(),
				"uom": frappe.db.get_value("Item", item_code, "stock_uom") or "Kg",
				"rate_type": "All-In Delivered",
				"valid_from": frappe.utils.today(),
			}).insert(ignore_permissions=True)


def _combination_to_dict(cc, results) -> Dict:
	raw = next((r for r in results if r["bom"] == cc.bom), {})
	return {
		"name": cc.name,
		"bom": cc.bom,
		"formulation_id": cc.formulation_id,
		"formulation_description": cc.formulation_description,
		"prev_rm_cost_per_kg": cc.prev_rm_cost_per_kg,
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

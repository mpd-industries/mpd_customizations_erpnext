from typing import Dict, List, Optional

import frappe
from frappe.utils import now_datetime

from mpd_customizations.costing.services.config import get_config
from mpd_customizations.costing.services.cost_calculator import (
	compute_additional_charge_amount,
	compute_credit_charge,
	compute_margin,
	compute_processing_cost,
	compute_rm_line_amount,
	compute_total_commission,
)
from mpd_customizations.costing.services.formulation_selector import FormulationSelector
from mpd_customizations.costing.services.freight_rate_fetcher import FreightRateFetcher
from mpd_customizations.costing.services.packaging_rate_fetcher import PackagingRateFetcher
from mpd_customizations.costing.services.rate_fetcher import RateFetcher
from mpd_customizations.costing.services.rate_source_registry import RateSourceRegistry


class CostingEngine:
	def __init__(self, registry: RateSourceRegistry, config=None):
		self._registry = registry
		self._config = config or get_config()

	def evaluate(self, pricing_calculation_name: str, trigger: str = "manual") -> Dict:
		doc = frappe.get_doc("Pricing Calculation", pricing_calculation_name)

		is_customer_quote = bool(doc.customer_product_ref)
		freight_fetch_result = None

		if is_customer_quote:
			boms = _get_customer_product_boms(doc.customer_product_ref)
			_init_packaging_lines(doc)
			_init_delivery_lines(doc)
			fetch_result = RateFetcher.fetch(doc, preserve_overrides=True, bom_list=boms)
			PackagingRateFetcher.fetch(doc, preserve_overrides=True)
			freight_fetch_result = FreightRateFetcher.fetch(doc, preserve_overrides=True)
		else:
			if not doc.item:
				frappe.throw(frappe._("Product is required."))
			if not doc.city:
				frappe.throw(frappe._("City is required on the Pricing Calculation."))

			bom_exists = frappe.db.exists("BOM", {"item": doc.item})
			if not bom_exists:
				frappe.throw(frappe._("No BOM found for item {0}.").format(doc.item))

			if doc.processor:
				processor_city = frappe.db.get_value("Processor", doc.processor, "city")
				if processor_city and processor_city != doc.city:
					frappe.throw(
						frappe._("Processor {0} is configured for city {1}, but this calculation is for city {2}.").format(
							doc.processor, processor_city, doc.city
						)
					)

			boms = frappe.get_all(
				"BOM",
				filters={"item": doc.item},
				fields=["name", "item", "quantity", "custom_formulation_id", "custom_formulation_description"],
			)
			fetch_result = RateFetcher.fetch(doc, preserve_overrides=True)

		doc.save(ignore_permissions=True)

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

		all_item_codes = {bi["item_code"] for bi in all_bom_items} | {si["item_code"] for si in all_scrap_items}
		item_label_map: Dict[str, str] = {}
		if all_item_codes:
			for row in frappe.get_all(
				"Item",
				filters={"name": ["in", list(all_item_codes)]},
				fields=["name", "custom_item_label"],
			):
				item_label_map[row.name] = row.custom_item_label or ""

		prev_rm_costs = {}
		preferred_bom_override = None
		if doc.pricing_request:
			prev_pc_name = frappe.db.get_value("Pricing Request", doc.pricing_request, "previous_pricing_ref")
			if prev_pc_name:
				prev_raw = frappe.parse_json(
					frappe.db.get_value("Pricing Calculation", prev_pc_name, "costing_raw") or "{}"
				)
				prev_combos = prev_raw.get("combinations", [])
				prev_rm_costs = {c["bom"]: c["rm_cost_per_kg"] for c in prev_combos}
				prev_selected = next((c for c in prev_combos if c.get("is_selected")), None)
				if prev_selected:
					preferred_bom_override = prev_selected["bom"]

		preferred_bom = preferred_bom_override or doc.preferred_bom
		if preferred_bom_override and preferred_bom_override != doc.preferred_bom:
			frappe.db.set_value("Pricing Calculation", pricing_calculation_name, "preferred_bom", preferred_bom_override)
			doc.preferred_bom = preferred_bom_override

		city = doc.city or ""
		rate_lines_map = {rl.item: rl for rl in (doc.rate_lines or [])}
		scrap_lines_map = {sl.item: sl for sl in (doc.scrap_lines or [])}
		processing_line = doc.processing_lines[0] if doc.processing_lines else None

		solids = doc.solids_content_pct or 0

		customer_credit_rate_pct = doc.customer_credit_rate_pct or self._config.customer_credit_rate_pct
		credit_days = 0
		margin_type = ""
		margin_rate = 0.0
		commissions = []
		if is_customer_quote:
			cp = frappe.get_doc("Customer Product", doc.customer_product_ref)
			credit_days = cp.credit_days or 0
			margin_type = cp.margin_type or ""
			margin_rate = cp.margin_rate or 0.0
			commissions = [
				{"rate": r.rate or 0, "commission_type": r.commission_type}
				for r in (cp.commissions or [])
			]

		# Sync fetched credit rate to doc for override tracking
		if doc.fetched_customer_credit_rate_pct != customer_credit_rate_pct:
			frappe.db.set_value(
				"Pricing Calculation", pricing_calculation_name,
				"fetched_customer_credit_rate_pct", customer_credit_rate_pct,
			)
		if not doc.customer_credit_rate_pct:
			frappe.db.set_value(
				"Pricing Calculation", pricing_calculation_name,
				"customer_credit_rate_pct", customer_credit_rate_pct,
			)
			doc.customer_credit_rate_pct = customer_credit_rate_pct

		if is_customer_quote and doc.credit_days != credit_days:
			frappe.db.set_value("Pricing Calculation", pricing_calculation_name, "credit_days", credit_days)

		additional_charges_per_kg = sum(
			compute_additional_charge_amount(c.rate or 0, c.basis, solids)
			for c in (doc.additional_charges or [])
		)

		# Packaging and delivery costs are constant across all combinations
		packaging_cost_per_kg = sum(
			(pl.packaging_cost_per_kg or 0) for pl in (doc.packaging_lines or [])
		)
		delivery_cost_per_kg = sum(
			(dl.working_freight_per_kg or 0) for dl in (doc.delivery_lines or [])
		)

		combination_results = []
		for bom in boms:
			bom_item_list = bom_items_map.get(bom["name"], [])
			bom_qty = bom["quantity"] or 1
			material_lines_data = []
			rm_cost = 0.0
			missing_items = []
			expired_items = []

			for bi in bom_item_list:
				qty_per_kg = (bi["qty"] or 0) / bom_qty
				rl = rate_lines_map.get(bi["item_code"])
				working_rate = (rl.working_rate or 0) if rl else 0.0
				fetched_rate = (rl.fetched_rate or 0) if rl else 0.0
				freshness = (rl.rate_freshness or "Missing") if rl else "Missing"
				supplier = (rl.supplier or None) if rl else None
				override_reason = (rl.override_reason or "") if rl else ""
				# Flag override when working ≠ fetched. Must include "missing rate" rows
				# (fetched_rate 0) with a non-zero working rate — old logic required fetched_rate
				# truthy, so provisional rates never appeared in the snapshot Rate Overrides table.
				_wr = round(working_rate or 0, 2)
				_fr = round(fetched_rate or 0, 2)
				is_overridden = bool(rl and _wr != _fr and (_fr > 0 or _wr > 0))

				amount = compute_rm_line_amount(qty_per_kg, working_rate)
				rm_cost += amount

				if freshness == "Missing":
					missing_items.append(bi["item_code"])
				elif freshness == "Expired":
					expired_items.append(bi["item_code"])

				material_lines_data.append({
					"pricing_calculation": pricing_calculation_name,
					"item": bi["item_code"],
					"item_name": bi["item_name"],
					"custom_item_label": _material_item_label(
						bi["item_code"], bi["item_name"], rl, item_label_map
					),
					"uom": bi["uom"],
					"qty_per_kg_output": qty_per_kg,
					"supplier": supplier,
					"city": city,
					"rate_freshness": freshness,
					"working_rate": working_rate,
					"fetched_rate": fetched_rate,
					"override_reason": override_reason,
					"is_overridden": is_overridden,
					"amount_per_kg": amount,
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
					"custom_item_label": _material_item_label(
						si["item_code"], si["item_name"], None, item_label_map
					),
					"uom": si["stock_uom"],
					"qty_per_kg_output": qty_per_kg,
					"supplier": None,
					"city": city,
					"rate_freshness": "Current",
					"working_rate": scrap_rate,
					"amount_per_kg": scrap_amount,
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

			# For customer quotes, outward freight comes from delivery_lines (not processing)

			total_cost_per_kg = rm_cost + processing_cost + additional_charges_per_kg + outward_freight + packaging_cost_per_kg + delivery_cost_per_kg
			margin = compute_margin(total_cost_per_kg, margin_type, margin_rate, solids)
			total_cost_per_kg_with_margin = total_cost_per_kg + margin
			credit_charge = compute_credit_charge(total_cost_per_kg_with_margin, credit_days, customer_credit_rate_pct)
			margin_with_credit_charge = total_cost_per_kg_with_margin + credit_charge
			commission = compute_total_commission(commissions, margin_with_credit_charge, solids)
			selling_price = total_cost_per_kg + credit_charge + commission + margin

			# Combination status based on rate quality (never blocks calculation)
			pkg_missing = any(
				(pl.rate_freshness == "Missing") for pl in (doc.packaging_lines or [])
			)
			pkg_expired = any(
				(pl.rate_freshness == "Expired") for pl in (doc.packaging_lines or [])
			)
			del_missing = any(
				(dl.rate_freshness == "Missing") for dl in (doc.delivery_lines or [])
			)
			del_expired = any(
				(dl.rate_freshness == "Expired") for dl in (doc.delivery_lines or [])
			)

			if missing_items or pkg_missing or del_missing:
				status = "Indicative — Rates Missing"
			elif expired_items or pkg_expired or del_expired:
				status = "Indicative — Rates Expired"
			else:
				status = "Ready to Quote"

			combination_results.append({
				"bom": bom["name"],
				"formulation_id": bom.get("custom_formulation_id") or "",
				"formulation_description": bom.get("custom_formulation_description") or "",
				"prev_rm_cost_per_kg": prev_rm_costs.get(bom["name"], 0) or 0,
				"rm_cost_per_kg": rm_cost,
				"processing_cost_per_kg": processing_cost,
				"additional_charges_per_kg": additional_charges_per_kg,
				"outward_freight_per_kg": outward_freight,
				"packaging_cost_per_kg": packaging_cost_per_kg,
				"delivery_cost_per_kg": delivery_cost_per_kg,
				"total_cost_per_kg": total_cost_per_kg,
				"credit_charge_per_kg": credit_charge,
				"commission_per_kg": commission,
				"margin_per_kg": margin,
				"selling_price_per_kg": selling_price,
				"freight_total_per_kg": outward_freight + delivery_cost_per_kg,
				"status": status,
				"processing_charge_ref": processing_charge_ref or "",
				"missing_items": ", ".join(missing_items),
				"expired_items": ", ".join(expired_items),
				"material_lines": material_lines_data,
			})

		selector = FormulationSelector(self._config)
		selection = selector.select(combination_results, preferred_bom)

		previously_selected_bom = doc.selected_combination or None

		now = now_datetime()

		for combo in combination_results:
			combo["is_preferred"] = bool(combo["bom"] == preferred_bom)
			combo["is_selected"] = bool(combo["bom"] == previously_selected_bom)

		costing_raw = {
			"evaluated_on": now.isoformat(),
			"engine_version": self._config.engine_version,
			"switch_alert": selection.switch_alert or "",
			"customer_credit_rate_pct": doc.customer_credit_rate_pct or 0,
			"credit_days": doc.credit_days or 0,
			"solids_content_pct": doc.solids_content_pct or 0,
			"additional_charges": [
				{
					"description": c.description,
					"basis": c.basis,
					"rate": c.rate or 0,
					"amount_per_kg": c.amount_per_kg or 0,
				}
				for c in (doc.additional_charges or [])
			],
			"combinations": combination_results,
		}

		selected_combo = next((c for c in combination_results if c.get("is_selected")), None)
		mode = "Ready to Quote" if selected_combo else "Ready for Working"
		update_fields = {
			"last_evaluated_on": now,
			"engine_version_used": self._config.engine_version,
			"mode": mode,
			"formulation_switch_alert": selection.switch_alert or "",
			"costing_raw": frappe.as_json(costing_raw),
			"selected_combination": selected_combo["bom"] if selected_combo else "",
			"confirmed_selling_price_per_kg": (selected_combo.get("selling_price_per_kg") or 0) if selected_combo else 0,
		}

		frappe.db.set_value("Pricing Calculation", pricing_calculation_name, update_fields)

		_sync_to_pricing_request(
			doc, mode,
			update_fields.get("confirmed_selling_price_per_kg"),
		)
		_update_pending_rate_items(doc, fetch_result, mode)
		if freight_fetch_result:
			_update_pending_freight_rates(doc, freight_fetch_result)

		fetch_result_payload = {
			"has_missing_rates": fetch_result.has_missing_rates,
			"missing_items": fetch_result.missing_items,
			"has_expired_rates": fetch_result.has_expired_rates,
			"expired_items": fetch_result.expired_items,
			"overrides_detected": fetch_result.overrides_detected,
			"overrides_changed": fetch_result.overrides_changed,
		}
		if freight_fetch_result:
			fetch_result_payload.update({
				"has_missing_freight": freight_fetch_result.has_missing_rates,
				"missing_freight_destinations": freight_fetch_result.missing_destinations,
				"has_expired_freight": freight_fetch_result.has_expired_rates,
				"expired_freight_destinations": freight_fetch_result.expired_destinations,
			})

		return {
			"combinations": combination_results,
			"fetch_result": fetch_result_payload,
			"switch_alert": selection.switch_alert,
			"mode": mode,
		}


def _get_customer_product_boms(customer_product_ref: str) -> List[Dict]:
	cp_status = frappe.db.get_value("Customer Product", customer_product_ref, "status")
	if cp_status != "Approved":
		frappe.throw(
			frappe._("Customer Product {0} must be Approved before costing.").format(customer_product_ref)
		)

	formulations = frappe.get_all(
		"Customer Product Formulation",
		filters={"parent": customer_product_ref, "parenttype": "Customer Product"},
		fields=["bom"],
	)
	if not formulations:
		frappe.throw(frappe._("Customer Product {0} has no formulations configured.").format(customer_product_ref))

	bom_names = [f["bom"] for f in formulations]
	boms = frappe.get_all(
		"BOM",
		filters={"name": ["in", bom_names]},
		fields=["name", "item", "quantity", "custom_formulation_id", "custom_formulation_description"],
	)
	return boms


def _init_packaging_lines(doc):
	if doc.packaging_lines:
		return
	cp = frappe.get_doc("Customer Product", doc.customer_product_ref)
	if cp.packaging_material:
		doc.append("packaging_lines", {
			"packaging_material": cp.packaging_material,
			"fill_quantity_kg": cp.fill_quantity_kg or 1.0,
		})


def _init_delivery_lines(doc):
	if doc.delivery_lines:
		return
	cp = frappe.get_doc("Customer Product", doc.customer_product_ref)
	if not cp.delivery_address:
		return
	source_address = ""
	source_city = ""
	if doc.processor:
		proc = frappe.db.get_value("Processor", doc.processor, ["address", "city"], as_dict=True) or {}
		source_address = proc.get("address") or ""
		source_city = proc.get("city") or ""
	doc.append("delivery_lines", {
		"source_address": source_address,
		"source_city": source_city,
		"destination_address": cp.delivery_address,
		"destination_city": cp.delivery_city or "",
		"destination_country": cp.delivery_country or "",
		"is_export": cp.is_export or 0,
		"transport_mode": cp.transport_mode or "Barrels",
		"incoterms": cp.incoterms or "",
		"rate_freshness": "Missing",
	})


def build_cost_summary(combo: dict, raw: dict) -> dict:
	"""Build accounting-head snapshot for Pricing Request (no material_lines)."""
	solids = raw.get("solids_content_pct") or combo.get("solids_content_pct")
	credit_days = raw.get("credit_days") or 0
	credit_rate = raw.get("customer_credit_rate_pct") or 0

	rm = combo.get("rm_cost_per_kg") or 0
	proc = combo.get("processing_cost_per_kg") or 0
	addl = combo.get("additional_charges_per_kg")
	if addl is None:
		add_charges = raw.get("additional_charges") or combo.get("additional_charges") or []
		addl = sum((c.get("amount_per_kg") or 0) for c in add_charges)
	else:
		addl = addl or 0
	pkg = combo.get("packaging_cost_per_kg") or 0
	freight = combo.get("outward_freight_per_kg") or combo.get("freight_total_per_kg") or 0
	margin = combo.get("margin_per_kg") or 0
	comm = combo.get("commission_per_kg") or 0
	credit = combo.get("credit_charge_per_kg") or 0
	selling = combo.get("selling_price_per_kg") or 0

	heads = []
	running = 0.0

	def _add(key: str, label: str, amount: float, *, is_total: bool = False):
		nonlocal running
		if not is_total:
			running += amount
		heads.append({
			"key": key,
			"label": label,
			"amount_per_kg": round(amount, 2),
			"running_total": round(selling if is_total else running, 2),
			**( {"is_total": True} if is_total else {} ),
		})

	_add("rm_cost", "RM Cost", rm)
	proc_label = "Processing"
	if solids and proc:
		proc_label = f"Processing ({solids}% solids)"
	_add("processing", proc_label, proc)
	_add("additional_charges", "Additional Charges", addl)
	_add("packaging", "Packaging", pkg)
	_add("freight", "Freight", freight)
	_add("margin", "Margin", margin)
	_add("commission", "Commission", comm)
	_add("credit_charge", f"Credit Charge ({credit_days}d @ {credit_rate}% pa)", credit)
	_add("selling_price", "Selling Price", selling, is_total=True)

	return {
		"formulation_id": combo.get("formulation_id"),
		"bom": combo.get("bom"),
		"credit_days": credit_days,
		"customer_credit_rate_pct": credit_rate,
		"solids_content_pct": solids,
		"heads": heads,
	}


def _material_item_label(
	item_code: str,
	item_name: str,
	rate_line=None,
	item_label_map: Optional[Dict[str, str]] = None,
) -> str:
	if rate_line and getattr(rate_line, "custom_item_label", None):
		return rate_line.custom_item_label
	if item_label_map and item_label_map.get(item_code):
		return item_label_map[item_code]
	return item_name or item_code


def find_selected_combo(combinations: list, selected_bom: Optional[str] = None):
	for combo in combinations:
		if combo.get("is_selected"):
			return combo
	if selected_bom:
		for combo in combinations:
			if combo.get("bom") == selected_bom:
				return combo
	return None


def _compute_mode(selected_combination) -> str:
	if selected_combination:
		return "Ready to Quote"
	return "Ready for Working"


def _sync_to_pricing_request(doc, mode: str, confirmed_selling_price=None):
	if not doc.pricing_request:
		return
	update = {"status": mode}
	if confirmed_selling_price:
		qty = frappe.db.get_value("Pricing Request", doc.pricing_request, "quantity_kg") or 0
		update["confirmed_price_per_kg"] = confirmed_selling_price
		update["total_price"] = qty * confirmed_selling_price
	frappe.db.set_value("Pricing Request", doc.pricing_request, update)


def _update_pending_rate_items(doc, fetch_result, mode: str):
	if not frappe.db.has_column("Material Rate", "pricing_calculation"):
		return

	frappe.db.delete("Material Rate", {
		"pricing_calculation": doc.name,
		"docstatus": 0,
		"requested_on": ["is", "set"],
	})

	items_to_request = list(fetch_result.missing_items)
	items_to_request += [i for i in fetch_result.expired_items if i not in items_to_request]

	if not items_to_request:
		return

	priority = "Normal"
	product = ""
	if doc.pricing_request:
		pr_values = frappe.db.get_value(
			"Pricing Request", doc.pricing_request, ["priority", "product"], as_dict=True
		) or {}
		priority = pr_values.get("priority") or "Normal"
		product = pr_values.get("product") or ""

	city = doc.city or ""
	for item_code in items_to_request:
		existing = frappe.db.exists("Material Rate", {
			"item": item_code,
			"city": city,
			"docstatus": 0,
		})
		if not existing and city:
			frappe.get_doc({
				"doctype": "Material Rate",
				"item": item_code,
				"city": city,
				"pricing_calculation": doc.name,
				"pricing_request": doc.pricing_request or "",
				"product": product,
				"priority": priority,
				"requested_on": frappe.utils.now_datetime(),
				"uom": frappe.db.get_value("Item", item_code, "stock_uom") or "Kg",
				"rate_type": "All-In Delivered",
				"valid_from": frappe.utils.today(),
			}).insert(ignore_permissions=True)


def _update_pending_freight_rates(doc, freight_fetch_result):
	if not frappe.db.has_column("Freight Rate", "pricing_calculation"):
		return

	frappe.db.delete("Freight Rate", {
		"pricing_calculation": doc.name,
		"docstatus": 0,
		"requested_on": ["is", "set"],
	})

	if not freight_fetch_result.has_missing_rates and not freight_fetch_result.has_expired_rates:
		return

	for line in doc.delivery_lines or []:
		if not line.destination_address or line.rate_freshness not in ("Missing", "Expired"):
			continue
		if not line.source_address:
			continue

		existing = frappe.db.exists("Freight Rate", {
			"source_address": line.source_address,
			"destination_address": line.destination_address,
			"transport_mode": line.transport_mode or "Barrels",
			"incoterms": line.incoterms or "",
			"docstatus": 0,
		})
		if existing:
			continue

		frappe.get_doc({
			"doctype": "Freight Rate",
			"source_address": line.source_address,
			"destination_address": line.destination_address,
			"transport_mode": line.transport_mode or "Barrels",
			"incoterms": line.incoterms or "",
			"pricing_calculation": doc.name,
			"pricing_request": doc.pricing_request or "",
			"requested_on": frappe.utils.now_datetime(),
			"valid_from": frappe.utils.today(),
		}).insert(ignore_permissions=True)



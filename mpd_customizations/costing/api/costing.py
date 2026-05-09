import frappe
from frappe import _
from frappe.utils import now_datetime

from mpd_customizations.costing.services.config import get_config
from mpd_customizations.costing.services.cost_calculator import (
	compute_additional_charge_amount,
	compute_financing_cost_for_line,
	compute_internal_earnings,
	compute_processing_cost,
	compute_rm_line_amount,
	compute_total_cost,
)
from mpd_customizations.costing.services.formulation_selector import FormulationSelector
from mpd_customizations.costing.services.rate_source_registry import get_default_registry


@frappe.whitelist()
def evaluate(pricing_calculation_name: str, trigger: str = "manual"):
	frappe.has_permission("Pricing Calculation", "write", throw=True)

	config = get_config()
	registry = get_default_registry()

	from mpd_customizations.costing.services.costing_engine import CostingEngine
	engine = CostingEngine(registry, config)
	return engine.evaluate(pricing_calculation_name, trigger)


@frappe.whitelist()
def get_combinations(pricing_calculation_name: str):
	frappe.has_permission("Pricing Calculation", "read", throw=True)

	combos = frappe.get_all(
		"Costing Combination",
		filters={"pricing_calculation": pricing_calculation_name},
		fields=[
			"name", "bom", "formulation_id", "formulation_description", "prev_rm_cost_per_kg",
			"rank", "delta_pct", "status",
			"is_preferred", "is_selected", "rm_cost_per_kg", "financing_cost_per_kg",
			"processing_cost_per_kg", "additional_charges_per_kg", "outward_freight_per_kg",
			"total_cost_per_kg", "missing_items", "expired_items",
		],
	)

	combo_names = [c.name for c in combos]
	if combo_names:
		material_lines = frappe.get_all(
			"Costing Material Line",
			filters={"combination": ["in", combo_names]},
			fields=[
				"combination", "item", "item_name", "uom", "qty_per_kg_output",
				"supplier", "city", "rate_freshness", "working_rate",
				"working_supplier_credit_days", "net_financed_days",
				"amount_per_kg", "financing_cost_per_kg", "equalized_amount_per_kg",
				"is_scrap", "confidence_score",
			],
		)
		ml_map = {}
		for ml in material_lines:
			ml_map.setdefault(ml.combination, []).append(ml)

		for combo in combos:
			combo["material_lines"] = ml_map.get(combo.name, [])

	return combos


@frappe.whitelist()
def select_combination(pricing_calculation_name: str, combination_name: str):
	frappe.has_permission("Pricing Calculation", "write", throw=True)

	frappe.db.set_value("Costing Combination", {"pricing_calculation": pricing_calculation_name}, "is_selected", 0)
	combo = frappe.get_doc("Costing Combination", combination_name)
	frappe.db.set_value("Costing Combination", combination_name, "is_selected", 1)

	doc = frappe.get_doc("Pricing Calculation", pricing_calculation_name)
	new_mode = "Ready to Quote" if combo.status in ("Ready to Quote", "Indicative — Rates Expired") else doc.mode
	frappe.db.set_value(
		"Pricing Calculation",
		pricing_calculation_name,
		{
			"selected_combination": combination_name,
			"confirmed_ex_factory_cost_per_kg": combo.total_cost_per_kg,
			"mode": new_mode,
		},
	)

	# Sync to Pricing Request
	if doc.pricing_request:
		qty = frappe.db.get_value("Pricing Request", doc.pricing_request, "quantity_kg") or 0
		frappe.db.set_value("Pricing Request", doc.pricing_request, {
			"status": new_mode,
			"confirmed_price_per_kg": combo.total_cost_per_kg,
			"total_price": qty * combo.total_cost_per_kg,
		})

	return {"confirmed_ex_factory_cost_per_kg": combo.total_cost_per_kg, "mode": new_mode}


@frappe.whitelist()
def apply_rate_override(
	pricing_calculation_name: str,
	item: str,
	working_rate: float,
	working_supplier_credit_days: int,
	reason: str = "",
):
	frappe.has_permission("Pricing Calculation", "write", throw=True)

	doc = frappe.get_doc("Pricing Calculation", pricing_calculation_name)
	for rl in doc.rate_lines:
		if rl.item == item:
			rl.working_rate = float(working_rate)
			rl.working_supplier_credit_days = int(working_supplier_credit_days)
			rl.override_reason = reason
			break

	doc.save(ignore_permissions=True)
	return _recompute_combinations(doc)


@frappe.whitelist()
def apply_processing_override(
	pricing_calculation_name: str,
	working_charge_per_kg: float,
	working_freight_per_unit: float,
	working_includes_outward_freight: int,
	reason: str = "",
):
	frappe.has_permission("Pricing Calculation", "write", throw=True)

	doc = frappe.get_doc("Pricing Calculation", pricing_calculation_name)
	if doc.processing_lines:
		pl = doc.processing_lines[0]
		pl.working_charge_per_kg = float(working_charge_per_kg)
		pl.working_freight_per_unit = float(working_freight_per_unit)
		pl.working_includes_outward_freight = int(working_includes_outward_freight)
		pl.override_reason = reason

	doc.save(ignore_permissions=True)
	return _recompute_combinations(doc)


@frappe.whitelist()
def revert_rate_override(pricing_calculation_name: str, item: str):
	frappe.has_permission("Pricing Calculation", "write", throw=True)

	doc = frappe.get_doc("Pricing Calculation", pricing_calculation_name)
	for rl in doc.rate_lines:
		if rl.item == item:
			rl.working_rate = rl.fetched_rate
			rl.working_supplier_credit_days = rl.fetched_supplier_credit_days
			rl.override_reason = ""
			break

	doc.save(ignore_permissions=True)
	return _recompute_combinations(doc)


@frappe.whitelist()
def recompute_combinations(pricing_calculation_name: str):
	frappe.has_permission("Pricing Calculation", "write", throw=True)
	doc = frappe.get_doc("Pricing Calculation", pricing_calculation_name)
	result = _recompute_combinations(doc)
	result["modified"] = frappe.utils.cstr(
		frappe.db.get_value("Pricing Calculation", pricing_calculation_name, "modified")
	)
	return result


@frappe.whitelist()
def revert_all_overrides(pricing_calculation_name: str):
	frappe.has_permission("Pricing Calculation", "write", throw=True)

	doc = frappe.get_doc("Pricing Calculation", pricing_calculation_name)
	for rl in doc.rate_lines:
		rl.working_rate = rl.fetched_rate
		rl.working_supplier_credit_days = rl.fetched_supplier_credit_days
		rl.override_reason = ""

	if doc.processing_lines:
		pl = doc.processing_lines[0]
		pl.working_charge_per_kg = pl.fetched_charge_per_kg
		pl.working_freight_per_unit = pl.fetched_freight_per_unit
		pl.working_includes_outward_freight = pl.fetched_includes_outward_freight
		pl.override_reason = ""

	doc.save(ignore_permissions=True)
	return _recompute_combinations(doc)


@frappe.whitelist()
def create_pending_rates(pricing_calculation_name: str):
	frappe.has_permission("Pricing Calculation", "write", throw=True)

	doc = frappe.get_doc("Pricing Calculation", pricing_calculation_name)
	priority = "Normal"
	product = ""
	if doc.pricing_request:
		pr_values = frappe.db.get_value(
			"Pricing Request", doc.pricing_request, ["priority", "product"], as_dict=True
		) or {}
		priority = pr_values.get("priority") or "Normal"
		product = pr_values.get("product") or ""

	if doc.rate_lines:
		items_needing_rates = [
			rl.item for rl in doc.rate_lines
			if rl.rate_freshness in ("Missing", "Expired")
		]
	else:
		items_needing_rates = _get_bom_items_without_current_rate(doc.item, doc.city)

	if not frappe.db.has_column("Material Rate", "pricing_calculation"):
		return {"created_count": 0, "error": "Run bench migrate first to add new fields to Material Rate"}

	created = 0
	for item in items_needing_rates:
		existing = frappe.db.exists(
			"Material Rate",
			{"item": item, "city": doc.city, "docstatus": 0},
		)
		if not existing:
			frappe.get_doc({
				"doctype": "Material Rate",
				"item": item,
				"city": doc.city,
				"pricing_calculation": pricing_calculation_name,
				"pricing_request": doc.pricing_request or "",
				"product": product,
				"priority": priority,
				"requested_on": now_datetime(),
				"uom": frappe.db.get_value("Item", item, "stock_uom") or "Kg",
				"rate_type": "All-In Delivered",
				"valid_from": frappe.utils.today(),
			}).insert(ignore_permissions=True)
			created += 1

	return {"created_count": created}


def _get_bom_items_without_current_rate(product_item: str, city: str) -> list:
	today = frappe.utils.today()
	boms = frappe.get_all(
		"BOM",
		filters={"item": product_item},
		fields=["name"],
	)
	if not boms:
		return []

	seen = set()
	result = []
	for bom in boms:
		bom_items = frappe.get_all(
			"BOM Item",
			filters={"parent": bom.name},
			fields=["item_code"],
		)
		for bi in bom_items:
			item_code = bi.item_code
			if item_code in seen:
				continue
			seen.add(item_code)
			has_rate = frappe.db.exists(
				"Material Rate",
				{
					"item": item_code,
					"city": city,
					"docstatus": 1,
					"valid_from": ["<=", today],
					"valid_to": [">=", today],
				},
			)
			if not has_rate:
				result.append(item_code)

	return result


@frappe.whitelist()
def get_cost_breakdown(pricing_calculation_name: str):
	frappe.has_permission("Pricing Calculation", "read", throw=True)

	doc = frappe.get_doc("Pricing Calculation", pricing_calculation_name)
	if not doc.selected_combination:
		return {}

	combo = frappe.get_doc("Costing Combination", doc.selected_combination)
	material_lines = frappe.get_all(
		"Costing Material Line",
		filters={"combination": doc.selected_combination},
		fields=[
			"item", "item_name", "uom", "qty_per_kg_output", "supplier", "city",
			"rate_freshness", "working_rate", "working_supplier_credit_days",
			"net_financed_days", "amount_per_kg", "financing_cost_per_kg",
			"equalized_amount_per_kg", "is_scrap",
		],
	)

	rate_lines_map = {rl.item: rl for rl in (doc.rate_lines or [])}
	for ml in material_lines:
		rl = rate_lines_map.get(ml.item)
		ml["fetched_rate"] = rl.fetched_rate if rl else None
		ml["rate_source_ref"] = rl.rate_source_ref if rl else None
		ml["is_overridden"] = bool(
			rl and rl.fetched_rate and
			round(rl.working_rate or 0, 2) != round(rl.fetched_rate, 2)
		)

	layer1 = {
		"formulation_id": combo.formulation_id,
		"bom": combo.bom,
		"material_lines": [dict(ml) for ml in material_lines],
		"rm_cost_per_kg": combo.rm_cost_per_kg,
		"financing_cost_per_kg": combo.financing_cost_per_kg,
		"processing_cost_per_kg": combo.processing_cost_per_kg,
		"additional_charges_per_kg": combo.additional_charges_per_kg,
		"additional_charges": [
			{"description": c.description, "basis": c.basis, "rate": c.rate, "amount_per_kg": c.amount_per_kg}
			for c in (doc.additional_charges or [])
		],
		"outward_freight_per_kg": combo.outward_freight_per_kg,
		"total_cost_per_kg": combo.total_cost_per_kg,
		"production_days": doc.production_days,
		"supplier_financing_rate_pct": doc.supplier_financing_rate_pct,
		"processing_charge_ref": combo.processing_charge_ref,
		"solids_content_pct": doc.solids_content_pct,
	}

	result = {"layer1": layer1}

	if set(frappe.get_roles(frappe.session.user)) & {"Costing Approver", "System Manager"}:
		config = get_config()
		ml_dicts = [
			{
				"item": ml["item"],
				"item_name": ml["item_name"],
				"amount_per_kg": ml["amount_per_kg"],
				"net_financed_days": ml["net_financed_days"],
			}
			for ml in material_lines
		]
		layer3 = compute_internal_earnings(
			ml_dicts,
			config.actual_cost_of_capital_pct,
			doc.supplier_financing_rate_pct or config.supplier_financing_rate_pct,
		)
		result["layer3"] = layer3

	return result


@frappe.whitelist()
def check_rate_conflict(
	item: str, supplier: str, city: str, valid_from: str, valid_to: str = None, exclude_name: str = None
):
	if not frappe.has_permission("Material Rate", "write"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	filters = {"item": item, "supplier": supplier, "city": city, "docstatus": 1}
	if exclude_name:
		filters["name"] = ["!=", exclude_name]

	existing = frappe.get_all(
		"Material Rate",
		filters=filters,
		fields=["name", "valid_from", "valid_to"],
	)

	from frappe.utils import getdate
	vf = getdate(valid_from)
	vt = getdate(valid_to) if valid_to else None
	far_future = getdate(frappe.utils.add_years(now_datetime(), 100))
	vt_cmp = vt if vt else far_future

	conflicts = []
	for e in existing:
		et_cmp = getdate(e.valid_to) if e.valid_to else far_future
		ef = getdate(e.valid_from)
		if ef < vt_cmp and et_cmp > vf:
			conflicts.append({"name": e.name, "valid_from": str(e.valid_from), "valid_to": str(e.valid_to)})

	return {"has_conflict": bool(conflicts), "conflicts": conflicts}


@frappe.whitelist()
def auto_expire_rate(rate_name: str, new_valid_to: str):
	if not frappe.has_permission("Material Rate", "write"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	frappe.db.set_value("Material Rate", rate_name, "valid_to", new_valid_to)
	return {"success": True}


def on_material_rate_submitted(doc, method):
	"""Hook: fires on_submit of Material Rate. Synchronously re-evaluate all affected PCs."""
	from mpd_customizations.costing.services.config import get_config
	from mpd_customizations.costing.services.rate_source_registry import get_default_registry
	from mpd_customizations.costing.services.costing_engine import CostingEngine

	open_calcs = frappe.get_all(
		"Pricing Calculation",
		filters={"mode": ["in", ["Awaiting Rates", "Ready for Working"]]},
		fields=["name", "owner"],
	)
	if not open_calcs:
		return

	for pc in open_calcs:
		has_relevant = frappe.db.exists(
			"Costing Rate Line",
			{"parent": pc.name, "item": doc.item, "rate_freshness": ["in", ["Missing", "Expired"]]},
		)
		if not has_relevant:
			continue
		try:
			CostingEngine(get_default_registry(), get_config()).evaluate(pc.name, "auto")
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"Auto-evaluate failed for {pc.name}")
			continue
		frappe.publish_realtime(
			"eval_js",
			f"if(cur_frm&&cur_frm.doctype==='Pricing Calculation'&&cur_frm.docname==='{pc.name}'){{cur_frm.reload_doc();frappe.show_alert({{message:'Rates updated — calculation refreshed',indicator:'green'}});}}",
			user=pc.owner,
		)


@frappe.whitelist()
def approve_pricing_calculation(pricing_calculation_name: str):
	if not set(frappe.get_roles()) & {"Costing Approver", "System Manager"}:
		frappe.throw(_("Only Costing Approvers can approve."), frappe.PermissionError)

	pc = frappe.get_doc("Pricing Calculation", pricing_calculation_name)
	pc.mode = "Approved"
	pc.submit()  # sets docstatus=1, fires before_submit validation

	if pc.pricing_request:
		frappe.db.set_value("Pricing Request", pc.pricing_request, "status", "Approved")
		pr_docstatus = frappe.db.get_value("Pricing Request", pc.pricing_request, "docstatus")
		if pr_docstatus == 0:
			frappe.db.set_value("Pricing Request", pc.pricing_request, "docstatus", 1)

	return {"success": True}


@frappe.whitelist()
def reject_pricing_calculation(pricing_calculation_name: str):
	if not set(frappe.get_roles()) & {"Costing Approver", "System Manager"}:
		frappe.throw(_("Only Costing Approvers can reject."), frappe.PermissionError)

	pc = frappe.get_doc("Pricing Calculation", pricing_calculation_name)
	frappe.db.set_value("Pricing Calculation", pricing_calculation_name, "mode", "Rejected")

	if pc.pricing_request:
		frappe.db.set_value("Pricing Request", pc.pricing_request, "status", "Rejected")

	return {"success": True}


@frappe.whitelist()
def fetch_processing_charge(pricing_calculation_name: str):
	frappe.has_permission("Pricing Calculation", "write", throw=True)

	from mpd_customizations.costing.services.rate_fetcher import _get_processing_charge

	doc = frappe.get_doc("Pricing Calculation", pricing_calculation_name)
	if not doc.processor or not doc.item:
		return None

	pc = _get_processing_charge(doc.processor, doc.item, now_datetime())
	if not pc:
		return None

	existing_pl = doc.processing_lines[0] if doc.processing_lines else None
	if existing_pl:
		existing_pl.fetched_charge_per_kg = pc["charge_per_kg"]
		existing_pl.fetched_freight_per_unit = pc.get("fg_freight_per_unit") or 0
		existing_pl.fetched_includes_outward_freight = pc.get("includes_outward_freight")
		existing_pl.working_charge_per_kg = pc["charge_per_kg"]
		existing_pl.working_freight_per_unit = pc.get("fg_freight_per_unit") or 0
		existing_pl.working_includes_outward_freight = pc.get("includes_outward_freight")
		existing_pl.processing_charge_ref = pc["name"]
		existing_pl.processor = doc.processor
	else:
		doc.append("processing_lines", {
			"processor": doc.processor,
			"processing_charge_ref": pc["name"],
			"fetched_charge_per_kg": pc["charge_per_kg"],
			"fetched_freight_per_unit": pc.get("fg_freight_per_unit") or 0,
			"fetched_includes_outward_freight": pc.get("includes_outward_freight"),
			"working_charge_per_kg": pc["charge_per_kg"],
			"working_freight_per_unit": pc.get("fg_freight_per_unit") or 0,
			"working_includes_outward_freight": pc.get("includes_outward_freight"),
		})

	doc.save(ignore_permissions=True)
	return {"charge_per_kg": pc["charge_per_kg"], "ref": pc["name"]}


def _recompute_combinations(doc) -> dict:
	"""After an override update, recompute all combination costs and re-rank."""
	config = get_config()
	production_days = doc.production_days or 30
	financing_rate = doc.supplier_financing_rate_pct or 12.0
	solids = doc.solids_content_pct or 0
	rate_lines_map = {rl.item: rl for rl in (doc.rate_lines or [])}
	scrap_lines_map = {sl.item: sl for sl in (doc.scrap_lines or [])}
	processing_line = doc.processing_lines[0] if doc.processing_lines else None

	additional_charges_per_kg = sum(
		compute_additional_charge_amount(c.rate or 0, c.basis, solids)
		for c in (doc.additional_charges or [])
	)

	combos = frappe.get_all(
		"Costing Combination",
		filters={"pricing_calculation": doc.name},
		fields=["name", "bom"],
	)

	combination_totals = []
	for combo in combos:
		material_lines = frappe.get_all(
			"Costing Material Line",
			filters={"combination": combo.name},
			fields=["item", "item_name", "qty_per_kg_output", "rate_freshness", "net_financed_days", "is_scrap"],
		)

		rm_cost = 0.0
		financing_cost = 0.0
		missing_items = []
		expired_items = []

		for ml in material_lines:
			is_scrap = ml.get("is_scrap")
			qty = ml.qty_per_kg_output or 0

			if is_scrap:
				sl = scrap_lines_map.get(ml.item)
				scrap_rate = (sl.rate_per_kg or 0) if sl else 0.0
				amount = -1 * compute_rm_line_amount(qty, scrap_rate)
				working_rate = scrap_rate
				credit_days = 0
				freshness = "Current"
				net_financed = 0
				fin = 0.0
			else:
				rl = rate_lines_map.get(ml.item)
				working_rate = (rl.working_rate or 0) if rl else 0.0
				credit_days = (rl.working_supplier_credit_days or 0) if rl else 0
				freshness = (rl.rate_freshness or "Missing") if rl else "Missing"
				net_financed = max(0, production_days - 60)
				amount = compute_rm_line_amount(qty, working_rate)
				fin = compute_financing_cost_for_line(amount, production_days, 60, financing_rate)

			rm_cost += amount
			financing_cost += fin

			frappe.db.set_value(
				"Costing Material Line",
				{"combination": combo.name, "item": ml.item},
				{
					"working_rate": working_rate,
					"working_supplier_credit_days": credit_days,
					"net_financed_days": net_financed,
					"amount_per_kg": amount,
					"financing_cost_per_kg": fin,
					"equalized_amount_per_kg": amount,
					"rate_freshness": freshness,
				},
			)

			if not ml.get("is_scrap"):
				if freshness == "Missing":
					missing_items.append(ml.item)
				elif freshness == "Expired":
					expired_items.append(ml.item)

		processing_cost = 0.0
		outward_freight = 0.0
		if processing_line:
			processing_cost = compute_processing_cost(solids, processing_line.working_charge_per_kg or 0)
			if not processing_line.working_includes_outward_freight:
				outward_freight = processing_line.working_freight_per_unit or 0

		total = compute_total_cost(rm_cost, financing_cost, processing_cost, additional_charges_per_kg, outward_freight)

		if missing_items:
			status = "Indicative — Rates Missing"
		elif expired_items:
			status = "Indicative — Rates Expired"
		else:
			status = "Ready to Quote"

		combination_totals.append({
			"name": combo.name,
			"bom": combo.bom,
			"rm_cost_per_kg": rm_cost,
			"financing_cost_per_kg": financing_cost,
			"processing_cost_per_kg": processing_cost,
			"additional_charges_per_kg": additional_charges_per_kg,
			"outward_freight_per_kg": outward_freight,
			"total_cost_per_kg": total,
			"status": status,
			"missing_items": ", ".join(missing_items),
			"expired_items": ", ".join(expired_items),
		})

	selector = FormulationSelector(config)
	selection = selector.select(combination_totals, doc.preferred_bom)

	for combo_data in combination_totals:
		frappe.db.set_value(
			"Costing Combination",
			combo_data["name"],
			{
				"rm_cost_per_kg": combo_data["rm_cost_per_kg"],
				"financing_cost_per_kg": combo_data["financing_cost_per_kg"],
				"processing_cost_per_kg": combo_data["processing_cost_per_kg"],
				"additional_charges_per_kg": combo_data["additional_charges_per_kg"],
				"outward_freight_per_kg": combo_data["outward_freight_per_kg"],
				"total_cost_per_kg": combo_data["total_cost_per_kg"],
				"status": combo_data["status"],
				"rank": combo_data.get("rank") or 0,
				"delta_pct": combo_data.get("delta_pct") or 0,
				"missing_items": combo_data["missing_items"],
				"expired_items": combo_data["expired_items"],
			},
		)

	if doc.selected_combination:
		selected = next((c for c in combination_totals if c["name"] == doc.selected_combination), None)
		if selected:
			frappe.db.set_value(
				"Pricing Calculation",
				doc.name,
				"confirmed_ex_factory_cost_per_kg",
				selected["total_cost_per_kg"],
			)
			# Sync to Pricing Request
			if doc.pricing_request:
				qty = frappe.db.get_value("Pricing Request", doc.pricing_request, "quantity_kg") or 0
				frappe.db.set_value("Pricing Request", doc.pricing_request, {
					"confirmed_price_per_kg": selected["total_cost_per_kg"],
					"total_price": qty * selected["total_cost_per_kg"],
				})

	frappe.db.set_value(
		"Pricing Calculation",
		doc.name,
		"formulation_switch_alert",
		selection.switch_alert or "",
	)

	return {
		"combinations": combination_totals,
		"switch_alert": selection.switch_alert,
		"modified": frappe.utils.cstr(doc.modified),
	}

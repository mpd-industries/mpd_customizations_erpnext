import frappe
from frappe import _
from frappe.utils import now_datetime

from mpd_customizations.costing.services.config import get_config
from mpd_customizations.costing.services.cost_calculator import compute_internal_earnings
from mpd_customizations.costing.services.rate_source_registry import get_default_registry

STANDARD_COSTED_PRICE_LIST = "Standard Costed"
QUOTE_VALIDITY_DAYS = 14


@frappe.whitelist()
def evaluate(pricing_calculation_name: str, trigger: str = "manual"):
	frappe.has_permission("Pricing Calculation", "write", throw=True)
	return _run_evaluate(pricing_calculation_name, trigger)


def _run_evaluate(pricing_calculation_name: str, trigger: str = "override"):
	from mpd_customizations.costing.services.costing_engine import CostingEngine
	return CostingEngine(get_default_registry(), get_config()).evaluate(pricing_calculation_name, trigger)


@frappe.whitelist()
def get_combinations(pricing_calculation_name: str):
	frappe.has_permission("Pricing Calculation", "read", throw=True)
	raw = frappe.db.get_value("Pricing Calculation", pricing_calculation_name, "costing_raw")
	return frappe.parse_json(raw or "{}").get("combinations", [])


@frappe.whitelist()
def select_combination(pricing_calculation_name: str, bom: str):
	frappe.has_permission("Pricing Calculation", "write", throw=True)

	raw_str = frappe.db.get_value("Pricing Calculation", pricing_calculation_name, "costing_raw")
	raw = frappe.parse_json(raw_str or "{}")
	combos = raw.get("combinations", [])

	selected = None
	for c in combos:
		c["is_selected"] = (c["bom"] == bom)
		if c["bom"] == bom:
			selected = c

	if not selected:
		frappe.throw(frappe._(f"BOM {bom} not found in costing data — please re-evaluate."))

	doc = frappe.get_doc("Pricing Calculation", pricing_calculation_name)
	new_mode = "Ready to Quote" if selected["status"] in ("Ready to Quote", "Indicative — Rates Expired") else doc.mode
	selling_price = selected.get("selling_price_per_kg") or selected["total_cost_per_kg"]

	frappe.db.set_value("Pricing Calculation", pricing_calculation_name, {
		"costing_raw": frappe.as_json(raw),
		"selected_combination": bom,
		"confirmed_selling_price_per_kg": selling_price,
		"mode": new_mode,
	})

	if doc.pricing_request:
		qty = frappe.db.get_value("Pricing Request", doc.pricing_request, "quantity_kg") or 0
		frappe.db.set_value("Pricing Request", doc.pricing_request, {
			"status": new_mode,
			"confirmed_price_per_kg": selling_price,
			"total_price": qty * selling_price,
		})

	return {"selling_price_per_kg": selling_price, "mode": new_mode}


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
	return _run_evaluate(pricing_calculation_name)


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
	return _run_evaluate(pricing_calculation_name)


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
	return _run_evaluate(pricing_calculation_name)


@frappe.whitelist()
def recompute_combinations(pricing_calculation_name: str):
	frappe.has_permission("Pricing Calculation", "write", throw=True)
	return _run_evaluate(pricing_calculation_name)


@frappe.whitelist()
def promote_freight_overrides_to_master(pricing_calculation_name: str):
	frappe.has_permission("Pricing Calculation", "write", throw=True)

	doc = frappe.get_doc("Pricing Calculation", pricing_calculation_name)

	source_address = ""
	if doc.processor:
		source_address = frappe.db.get_value("Processor", doc.processor, "address") or ""

	created = []
	skipped = []

	for dl in doc.delivery_lines or []:
		working_rate = dl.working_freight_per_kg or 0
		if not working_rate:
			continue

		is_missing = dl.rate_freshness == "Missing"
		is_overridden = round(working_rate, 4) != round(dl.fetched_freight_per_kg or 0, 4)
		if not (is_missing or is_overridden):
			continue

		dest_address = dl.destination_address
		if not dest_address or not source_address:
			skipped.append(dest_address or "Unknown")
			continue

		transport_mode = dl.transport_mode or "Barrels"

		existing = frappe.db.exists("Freight Rate", {
			"source_address": source_address,
			"destination_address": dest_address,
			"transport_mode": transport_mode,
			"docstatus": 0,
		})
		if existing:
			skipped.append(existing)
			continue

		new_doc = frappe.get_doc({
			"doctype": "Freight Rate",
			"source_address": source_address,
			"destination_address": dest_address,
			"transport_mode": transport_mode,
			"freight_per_kg": working_rate,
			"currency": dl.working_currency or "",
			"forex_rate": dl.working_forex_rate or 0,
			"valid_from": frappe.utils.today(),
		})
		new_doc.insert(ignore_permissions=True)
		created.append({"name": new_doc.name, "destination": dest_address, "transport_mode": transport_mode})

	return {"created": created, "skipped": skipped}


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
	return _run_evaluate(pricing_calculation_name)


def _notify_dispatch_team(pricing_request: str, routes: list):
	dispatch_users = frappe.get_all(
		"Has Role",
		filters={"role": "Dispatch Manager", "parenttype": "User"},
		fields=["parent"],
	)
	for u in dispatch_users:
		links = ", ".join(
			f'<a href="/app/freight-rate/{r["name"]}">{r["dest"]} ({r["mode"]})</a>'
			for r in routes
		)
		pr_part = f" for <a href='/app/pricing-request/{pricing_request}'>{pricing_request}</a>" if pricing_request else ""
		frappe.publish_realtime(
			"eval_js",
			f"frappe.show_alert({{message: 'Freight rate needed{pr_part}: {links}', indicator: 'orange'}})",
			user=u.parent,
		)


@frappe.whitelist()
def get_cost_breakdown(pricing_calculation_name: str):
	frappe.has_permission("Pricing Calculation", "read", throw=True)

	doc = frappe.get_doc("Pricing Calculation", pricing_calculation_name)
	if not doc.selected_combination:
		return {}

	raw = frappe.parse_json(doc.costing_raw or "{}") if hasattr(frappe, "parse_json") else __import__("json").loads(doc.costing_raw or "{}")
	combo = next((c for c in raw.get("combinations", []) if c["bom"] == doc.selected_combination), None)
	if not combo:
		return {}

	layer1 = {
		**combo,
		"additional_charges": raw.get("additional_charges", []),
		"production_days": raw.get("production_days", 0),
		"supplier_financing_rate_pct": raw.get("supplier_financing_rate_pct", 0),
		"customer_credit_rate_pct": raw.get("customer_credit_rate_pct", 0),
		"credit_days": raw.get("credit_days", 0),
		"solids_content_pct": raw.get("solids_content_pct", 0),
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
			for ml in combo.get("material_lines", [])
		]
		layer3 = compute_internal_earnings(
			ml_dicts,
			config.actual_cost_of_capital_pct,
			raw.get("supplier_financing_rate_pct") or config.supplier_financing_rate_pct,
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

	if not pc.valid_until:
		pc.valid_until = frappe.utils.add_days(frappe.utils.today(), QUOTE_VALIDITY_DAYS)
		frappe.db.set_value("Pricing Calculation", pc.name, "valid_until", pc.valid_until)

	_upsert_standard_costed_price(pc)

	return {"success": True}


def _upsert_standard_costed_price(pc):
	if not frappe.db.exists("Price List", STANDARD_COSTED_PRICE_LIST):
		return

	rate = pc.confirmed_selling_price_per_kg
	if not rate:
		return

	uom = frappe.db.get_value("Item", pc.item, "stock_uom") or "Kg"
	valid_from = frappe.utils.today()
	valid_upto = pc.valid_until

	existing = frappe.db.get_value(
		"Item Price",
		{"item_code": pc.item, "price_list": STANDARD_COSTED_PRICE_LIST, "uom": uom},
		"name",
	)

	if existing:
		frappe.db.set_value("Item Price", existing, {
			"price_list_rate": rate,
			"valid_from": valid_from,
			"valid_upto": valid_upto,
			"reference": pc.name,
		})
	else:
		frappe.get_doc({
			"doctype": "Item Price",
			"item_code": pc.item,
			"price_list": STANDARD_COSTED_PRICE_LIST,
			"uom": uom,
			"price_list_rate": rate,
			"valid_from": valid_from,
			"valid_upto": valid_upto,
			"reference": pc.name,
		}).insert(ignore_permissions=True)


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


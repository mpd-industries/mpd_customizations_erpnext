import frappe
from frappe import _
from frappe.utils import now_datetime

from mpd_customizations.costing.services.config import get_config
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
	return {"saved": True}


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
	return {"saved": True}


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
	return {"saved": True}


_PARAM_MAP = {
	"production_days": "fetched_production_days",
	"supplier_financing_rate_pct": "fetched_supplier_financing_rate_pct",
	"customer_credit_rate_pct": "fetched_customer_credit_rate_pct",
}


@frappe.whitelist()
def revert_parameter_override(pricing_calculation_name: str, param_name: str):
	frappe.has_permission("Pricing Calculation", "write", throw=True)
	fetched_field = _PARAM_MAP.get(param_name)
	if not fetched_field:
		frappe.throw(_("Unknown parameter: {0}").format(param_name))
	val = frappe.db.get_value("Pricing Calculation", pricing_calculation_name, fetched_field)
	frappe.db.set_value("Pricing Calculation", pricing_calculation_name, param_name, val)
	return {"saved": True}


@frappe.whitelist()
def revert_freight_override(pricing_calculation_name: str, row_name: str):
	frappe.has_permission("Pricing Calculation", "write", throw=True)
	doc = frappe.get_doc("Pricing Calculation", pricing_calculation_name)
	for dl in doc.delivery_lines:
		if dl.name == row_name:
			dl.working_freight_per_kg = dl.fetched_freight_per_kg or 0
			break
	doc.save(ignore_permissions=True)
	return {"saved": True}


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

	for dl in doc.delivery_lines:
		if dl.fetched_freight_per_kg is not None:
			dl.working_freight_per_kg = dl.fetched_freight_per_kg

	doc.save(ignore_permissions=True)

	for param, fetched_field in _PARAM_MAP.items():
		fetched_val = frappe.db.get_value("Pricing Calculation", pricing_calculation_name, fetched_field)
		if fetched_val is not None:
			frappe.db.set_value("Pricing Calculation", pricing_calculation_name, param, fetched_val)

	return {"saved": True}


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
def approve_customer_product(name: str):
	if not set(frappe.get_roles()) & {"Costing Approver", "System Manager"}:
		frappe.throw(_("Only Costing Approvers can approve."), frappe.PermissionError)

	doc = frappe.get_doc("Customer Product", name)
	if doc.status != "Formulations Added":
		frappe.throw(
			_("Customer Product must be in 'Formulations Added' status to approve. Current status: {0}").format(
				doc.status or "Draft"
			)
		)
	if not doc.margin_type or not doc.margin_rate:
		frappe.throw(_("Margin type and rate are required before approval."))

	doc.status = "Approved"
	doc.approved_by = frappe.session.user
	doc.approved_on = now_datetime()
	doc.save()

	return {"success": True, "status": doc.status}


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


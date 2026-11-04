"""Pricing approval workflow and rate-conflict checks.

The whitelisted endpoints in costing/api/costing.py check permissions and
delegate here.
"""

import frappe
from frappe import _
from frappe.utils import add_days, add_years, getdate, now_datetime, today

STANDARD_COSTED_PRICE_LIST = "Standard Costed"
QUOTE_VALIDITY_DAYS = 14


def select_combination(pricing_calculation_name: str, bom: str):
	raw_str = frappe.db.get_value("Pricing Calculation", pricing_calculation_name, "costing_raw")
	raw = frappe.parse_json(raw_str or "{}")
	combos = raw.get("combinations", [])

	selected = None
	for c in combos:
		c["is_selected"] = c["bom"] == bom
		if c["bom"] == bom:
			selected = c

	if not selected:
		frappe.throw(frappe._(f"BOM {bom} not found in costing data — please re-evaluate."))

	doc = frappe.get_doc("Pricing Calculation", pricing_calculation_name)
	new_mode = (
		"Ready to Quote"
		if selected["status"] in ("Ready to Quote", "Indicative — Rates Expired")
		else doc.mode
	)
	selling_price = selected.get("selling_price_per_kg") or selected["total_cost_per_kg"]

	frappe.db.set_value(
		"Pricing Calculation",
		pricing_calculation_name,
		{
			"costing_raw": frappe.as_json(raw),
			"selected_combination": bom,
			"confirmed_selling_price_per_kg": selling_price,
			"mode": new_mode,
		},
	)

	if doc.pricing_request:
		qty = frappe.db.get_value("Pricing Request", doc.pricing_request, "quantity_kg") or 0
		frappe.db.set_value(
			"Pricing Request",
			doc.pricing_request,
			{
				"status": new_mode,
				"confirmed_price_per_kg": selling_price,
				"total_price": qty * selling_price,
			},
		)

	return {"selling_price_per_kg": selling_price, "mode": new_mode}


def check_rate_conflict(
	item: str, supplier: str, city: str, valid_from: str, valid_to: str = None, exclude_name: str = None
):
	filters = {"item": item, "supplier": supplier, "city": city, "docstatus": 1}
	if exclude_name:
		filters["name"] = ["!=", exclude_name]

	existing = frappe.get_all(
		"Material Rate",
		filters=filters,
		fields=["name", "valid_from", "valid_to"],
	)

	vf = getdate(valid_from)
	vt = getdate(valid_to) if valid_to else None
	far_future = getdate(add_years(now_datetime(), 100))
	vt_cmp = vt if vt else far_future

	conflicts = []
	for e in existing:
		et_cmp = getdate(e.valid_to) if e.valid_to else far_future
		ef = getdate(e.valid_from)
		if ef < vt_cmp and et_cmp > vf:
			conflicts.append({"name": e.name, "valid_from": str(e.valid_from), "valid_to": str(e.valid_to)})

	return {"has_conflict": bool(conflicts), "conflicts": conflicts}


def approve_customer_product(name: str):
	doc = frappe.get_doc("Customer Product", name)
	if doc.status != "Formulations Added":
		frappe.throw(
			_(
				"Customer Product must be in 'Formulations Added' status to approve. Current status: {0}"
			).format(doc.status or "Draft")
		)
	if not doc.margin_type or not doc.margin_rate:
		frappe.throw(_("Margin type and rate are required before approval."))

	doc.status = "Approved"
	doc.approved_by = frappe.session.user
	doc.approved_on = now_datetime()
	doc.save()

	return {"success": True, "status": doc.status}


def approve_pricing_calculation(pricing_calculation_name: str):
	pc = frappe.get_doc("Pricing Calculation", pricing_calculation_name)
	pc.mode = "Approved"
	pc.submit()  # sets docstatus=1, fires before_submit validation

	if pc.pricing_request:
		frappe.db.set_value("Pricing Request", pc.pricing_request, "status", "Approved")
		pr_docstatus = frappe.db.get_value("Pricing Request", pc.pricing_request, "docstatus")
		if pr_docstatus == 0:
			frappe.db.set_value("Pricing Request", pc.pricing_request, "docstatus", 1)

	if not pc.valid_until:
		pc.valid_until = add_days(today(), QUOTE_VALIDITY_DAYS)
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
	valid_from = today()
	valid_upto = pc.valid_until

	existing = frappe.db.get_value(
		"Item Price",
		{"item_code": pc.item, "price_list": STANDARD_COSTED_PRICE_LIST, "uom": uom},
		"name",
	)

	if existing:
		frappe.db.set_value(
			"Item Price",
			existing,
			{
				"price_list_rate": rate,
				"valid_from": valid_from,
				"valid_upto": valid_upto,
				"reference": pc.name,
			},
		)
	else:
		frappe.get_doc(
			{
				"doctype": "Item Price",
				"item_code": pc.item,
				"price_list": STANDARD_COSTED_PRICE_LIST,
				"uom": uom,
				"price_list_rate": rate,
				"valid_from": valid_from,
				"valid_upto": valid_upto,
				"reference": pc.name,
			}
		).insert(ignore_permissions=True)


def reject_pricing_calculation(pricing_calculation_name: str):
	pc = frappe.get_doc("Pricing Calculation", pricing_calculation_name)
	frappe.db.set_value("Pricing Calculation", pricing_calculation_name, "mode", "Rejected")

	if pc.pricing_request:
		frappe.db.set_value("Pricing Request", pc.pricing_request, "status", "Rejected")

	return {"success": True}

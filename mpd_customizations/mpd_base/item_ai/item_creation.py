"""Turn an Item Request into an ERPNext Item."""

import frappe


def canonical_request_description(doc) -> str:
	"""Prefer the combined description, then the requester's own text."""
	return (doc.combined_asset_description or "").strip() or (doc.requester_description or "").strip()


def _resolve_stock_uom_for_item(doc):
	"""Prefer user stock_uom, then AI, then Stock Settings, then Nos."""
	candidates = [
		doc.stock_uom,
		doc.ai_uom_suggestion,
		frappe.db.get_single_value("Stock Settings", "stock_uom"),
		"Nos",
	]
	for u in candidates:
		if u and frappe.db.exists("UOM", u):
			return u
	fallback = frappe.db.get_value("UOM", {}, "name")
	return fallback or "Nos"


def _resolve_gst_hsn_link_for_item(doc):
	"""Return a GST HSN Code document name for Item.gst_hsn_code Link, or empty string."""
	if not frappe.db.exists("DocType", "GST HSN Code"):
		return (doc.gst_hsn_code or doc.ai_hsn_suggestion or "").strip()
	raw = (doc.gst_hsn_code or doc.ai_hsn_suggestion or "").strip()
	if not raw:
		return ""
	if frappe.db.exists("GST HSN Code", raw):
		return raw
	name = frappe.db.get_value("GST HSN Code", {"hsn_code": raw}, "name")
	if name:
		return name
	frappe.log_error(
		title="GST HSN not found for Item",
		message=f"Could not resolve HSN {raw!r} for Item Request {doc.name}",
	)
	return ""


def build_and_insert_item(doc):
	"""
	Creates an ERPNext Item from the AI suggestion fields on the request doc.
	Returns the new item_code.
	"""
	if not doc.ai_item_name_suggestion:
		frappe.throw("AI item name suggestion is missing — cannot create item.")
	if not doc.ai_item_group_suggestion:
		frappe.throw("AI item group suggestion is missing — cannot create item.")

	prefix = doc.ai_prefix_suggestion or "GEN"

	# Build a sequential item code: PREFIX-XXXXX
	existing = frappe.db.count("Item", {"item_code": ["like", f"{prefix}-%"]})
	item_code = f"{prefix}-{str(existing + 1).zfill(5)}"

	# Avoid collision in the rare case of gaps/deletions
	while frappe.db.exists("Item", item_code):
		existing += 1
		item_code = f"{prefix}-{str(existing + 1).zfill(5)}"

	stock_uom = _resolve_stock_uom_for_item(doc)
	gst_link = _resolve_gst_hsn_link_for_item(doc)
	canonical_desc = canonical_request_description(doc)

	is_fixed_asset = 1 if doc.is_fixed_asset else 0
	is_stock_item = 1 if doc.is_stock_item and not is_fixed_asset else 0
	# Expense: both flags stay 0.

	if is_fixed_asset and not doc.ai_asset_category_suggestion:
		frappe.throw("Asset Category is required for Fixed Asset items — pick or keep the AI suggestion.")

	item = frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": item_code,
			"item_name": doc.ai_item_name_suggestion,
			"description": canonical_desc,
			"item_group": doc.ai_item_group_suggestion,
			"is_stock_item": is_stock_item,
			"is_fixed_asset": is_fixed_asset,
			"is_purchase_item": 1,
			"stock_uom": stock_uom,
			"purchase_uom": stock_uom,
			"gst_hsn_code": gst_link,
			"asset_category": doc.ai_asset_category_suggestion or None,
		}
	)

	item.custom_item_request = doc.name

	# Carry over legacy codes if present
	if doc.tally_name:
		item.custom_tally_name = doc.tally_name
	if doc.tally_alias:
		item.custom_tally_alias = doc.tally_alias
	if doc.legacy_material_code:
		item.custom_legacy_code = doc.legacy_material_code

	item.insert(ignore_permissions=True)
	return item_code

import frappe


def on_trash(doc, method=None):
    if doc.custom_item_request:
        frappe.db.set_value("Item Request", doc.custom_item_request, "created_item_code", None)

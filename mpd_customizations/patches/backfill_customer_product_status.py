import frappe


def execute():
	if not frappe.db.table_exists("tabCustomer Product"):
		return

	if not frappe.db.has_column("Customer Product", "status"):
		return

	products = frappe.get_all("Customer Product", pluck="name")
	updated = 0

	for name in products:
		current = frappe.db.get_value("Customer Product", name, "status")
		if current:
			continue

		has_bom = frappe.db.exists(
			"Customer Product Formulation",
			{"parent": name, "parenttype": "Customer Product", "bom": ["!=", ""]},
		)
		status = "Formulations Added" if has_bom else "Draft"
		frappe.db.set_value("Customer Product", name, "status", status, update_modified=False)
		updated += 1

	if updated:
		frappe.db.commit()
		print(f"Backfilled status for {updated} Customer Product(s).")

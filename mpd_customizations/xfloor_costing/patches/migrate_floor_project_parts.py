import frappe

from mpd_customizations.xfloor_costing.services.pl_engine import flat_fields_to_main_part


def execute():
	if not frappe.db.table_exists("Floor Project"):
		return
	if not frappe.db.table_exists("Floor Project Part"):
		return

	projects = frappe.get_all("Floor Project", pluck="name")
	migrated = 0

	for name in projects:
		doc = frappe.get_doc("Floor Project", name)
		if doc.get("parts"):
			continue

		part = flat_fields_to_main_part(
			{
				"sqft": doc.sqft,
				"top_coat_option": doc.top_coat_option,
				"screed_option": doc.screed_option,
				"applicator_rate": doc.applicator_rate,
			}
		)
		doc.append("parts", part)
		doc.save(ignore_permissions=True)
		migrated += 1

	if migrated:
		frappe.db.commit()
		print(f"Migrated {migrated} Floor Project(s) to parts model.")

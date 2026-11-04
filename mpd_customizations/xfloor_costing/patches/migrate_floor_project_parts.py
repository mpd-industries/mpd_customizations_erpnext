import frappe

from mpd_customizations.xfloor_costing.services.pl_engine import flat_fields_to_main_part


def execute():
	if not frappe.db.table_exists("Floor Project"):
		return
	if not frappe.db.table_exists("Floor Project Part"):
		return

	projects = frappe.get_all("Floor Project", pluck="name")
	migrated = 0
	backfilled = 0

	for name in projects:
		doc = frappe.get_doc("Floor Project", name)
		changed = False

		if not doc.get("parts"):
			doc.append(
				"parts",
				flat_fields_to_main_part(
					{
						"sqft": doc.sqft,
						"rate_per_sqft": doc.rate_per_sqft,
						"top_coat_option": doc.top_coat_option,
						"screed_option": doc.screed_option,
						"coving_kits": doc.coving_kits,
						"hibuild_kits": doc.hibuild_kits,
						"applicator_rate": doc.applicator_rate,
					}
				),
			)
			changed = True
			migrated += 1
		else:
			# Existing parts from earlier migrate: copy parent rate/kits if parts still empty.
			parent_rate = float(doc.rate_per_sqft or 0)
			parent_coving = float(doc.coving_kits or 0)
			parent_hibuild = float(doc.hibuild_kits or 0)
			if parent_rate and all(not float(p.rate_per_sqft or 0) for p in doc.parts):
				for p in doc.parts:
					p.rate_per_sqft = parent_rate
				changed = True
			if parent_coving and all(not float(p.coving_kits or 0) for p in doc.parts):
				doc.parts[0].coving_kits = parent_coving
				changed = True
			if parent_hibuild and all(not float(p.hibuild_kits or 0) for p in doc.parts):
				doc.parts[0].hibuild_kits = parent_hibuild
				changed = True
			if changed:
				backfilled += 1

		if changed:
			doc.save(ignore_permissions=True)

	if migrated or backfilled:
		frappe.db.commit()
		print(
			f"Migrated {migrated} Floor Project(s) to parts; "
			f"backfilled rate/kits on {backfilled} existing part-set(s)."
		)

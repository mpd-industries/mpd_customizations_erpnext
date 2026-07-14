import frappe


def execute():
	"""Backfill per-part rate / coving / hibuild from project rollup fields."""
	if not frappe.db.table_exists("Floor Project"):
		return
	if not frappe.db.table_exists("Floor Project Part"):
		return
	if not frappe.db.has_column("Floor Project Part", "rate_per_sqft"):
		return

	updated = 0
	for name in frappe.get_all("Floor Project", pluck="name"):
		doc = frappe.get_doc("Floor Project", name)
		parts = doc.get("parts") or []
		if not parts:
			continue

		parent_rate = float(doc.rate_per_sqft or 0)
		parent_coving = float(doc.coving_kits or 0)
		parent_hibuild = float(doc.hibuild_kits or 0)
		changed = False

		if parent_rate and all(not float(p.rate_per_sqft or 0) for p in parts):
			for p in parts:
				p.rate_per_sqft = parent_rate
			changed = True
		if parent_coving and all(not float(p.coving_kits or 0) for p in parts):
			parts[0].coving_kits = parent_coving
			changed = True
		if parent_hibuild and all(not float(p.hibuild_kits or 0) for p in parts):
			parts[0].hibuild_kits = parent_hibuild
			changed = True

		if changed:
			doc.save(ignore_permissions=True)
			updated += 1

	if updated:
		frappe.db.commit()
		print(f"Backfilled per-part rate/kits on {updated} Floor Project(s).")

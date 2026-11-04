import frappe


def execute():
	"""Set project_number = name so unique index can be added safely.

	Legacy rows used short manual numbers (e.g. '002') that collide across projects.
	Autoname docs already use unique names (XFP-.YYYY.-.#####).
	"""
	if not frappe.db.table_exists("Floor Project"):
		return
	if not frappe.db.has_column("Floor Project", "project_number"):
		return

	rows = frappe.db.sql(
		"""
		SELECT name, project_number
		FROM `tabFloor Project`
		WHERE IFNULL(project_number, '') != name
		""",
		as_dict=True,
	)
	for row in rows:
		frappe.db.set_value(
			"Floor Project",
			row.name,
			"project_number",
			row.name,
			update_modified=False,
		)

	if rows:
		frappe.db.commit()
		print(f"Synced project_number to name for {len(rows)} Floor Project(s).")

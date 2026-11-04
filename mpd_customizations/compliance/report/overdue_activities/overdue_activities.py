import frappe


def execute(filters=None):
	columns = [
		{"label": "Title", "fieldname": "title", "fieldtype": "Data", "width": 240},
		{"label": "Company", "fieldname": "company", "fieldtype": "Link", "options": "Company", "width": 160},
		{
			"label": "Site",
			"fieldname": "site",
			"fieldtype": "Link",
			"options": "Compliance Site",
			"width": 140,
		},
		{
			"label": "Domain",
			"fieldname": "domain",
			"fieldtype": "Link",
			"options": "Compliance Domain",
			"width": 160,
		},
		{"label": "Due", "fieldname": "due_date", "fieldtype": "Date", "width": 110},
		{"label": "Days Late", "fieldname": "days_late", "fieldtype": "Int", "width": 90},
		{
			"label": "Owner",
			"fieldname": "responsible_user",
			"fieldtype": "Link",
			"options": "User",
			"width": 140,
		},
	]
	data = frappe.get_all(
		"Compliance Activity",
		filters={"is_overdue": 1, "status": ["not in", ["Completed", "Not Applicable", "Waived"]]},
		fields=[c["fieldname"] for c in columns],
		order_by="due_date asc",
	)
	return columns, data

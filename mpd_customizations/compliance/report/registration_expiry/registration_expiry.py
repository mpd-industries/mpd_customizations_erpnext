import frappe


def execute(filters=None):
	columns = [
		{"label": "Type", "fieldname": "registration_type", "fieldtype": "Data", "width": 180},
		{"label": "Number", "fieldname": "registration_number", "fieldtype": "Data", "width": 160},
		{"label": "Company", "fieldname": "company", "fieldtype": "Link", "options": "Company", "width": 160},
		{
			"label": "Site",
			"fieldname": "site",
			"fieldtype": "Link",
			"options": "Compliance Site",
			"width": 140,
		},
		{"label": "Valid To", "fieldname": "valid_to", "fieldtype": "Date", "width": 110},
		{"label": "Status", "fieldname": "status", "fieldtype": "Data", "width": 100},
	]
	data = frappe.get_all(
		"Compliance Registration",
		filters={"status": ["in", ["Active", "Expired"]]},
		fields=[c["fieldname"] for c in columns],
		order_by="valid_to asc",
	)
	return columns, data

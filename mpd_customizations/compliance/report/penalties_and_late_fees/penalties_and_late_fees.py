import frappe


def execute(filters=None):
	columns = [
		{"label": "Title", "fieldname": "title", "fieldtype": "Data", "width": 240},
		{"label": "Company", "fieldname": "company", "fieldtype": "Link", "options": "Company", "width": 160},
		{
			"label": "Domain",
			"fieldname": "domain",
			"fieldtype": "Link",
			"options": "Compliance Domain",
			"width": 160,
		},
		{"label": "Period", "fieldname": "period_label", "fieldtype": "Data", "width": 120},
		{"label": "Late Fee", "fieldname": "late_fee_or_penalty", "fieldtype": "Currency", "width": 120},
		{"label": "Amount Paid", "fieldname": "amount_paid", "fieldtype": "Currency", "width": 120},
	]
	data = frappe.get_all(
		"Compliance Activity",
		filters={"late_fee_or_penalty": [">", 0]},
		fields=[c["fieldname"] for c in columns],
	)
	return columns, data

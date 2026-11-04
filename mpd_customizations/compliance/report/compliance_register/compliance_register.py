import frappe


def execute(filters=None):
	columns = [
		{"label": "Title", "fieldname": "title", "fieldtype": "Data", "width": 220},
		{
			"label": "Domain",
			"fieldname": "domain",
			"fieldtype": "Link",
			"options": "Compliance Domain",
			"width": 160,
		},
		{"label": "Scope", "fieldname": "scope", "fieldtype": "Data", "width": 90},
		{"label": "Company", "fieldname": "company", "fieldtype": "Link", "options": "Company", "width": 160},
		{
			"label": "Site",
			"fieldname": "site",
			"fieldtype": "Link",
			"options": "Compliance Site",
			"width": 140,
		},
		{"label": "Frequency", "fieldname": "frequency", "fieldtype": "Data", "width": 110},
		{"label": "Status", "fieldname": "status", "fieldtype": "Data", "width": 90},
		{
			"label": "Owner",
			"fieldname": "responsible_user",
			"fieldtype": "Link",
			"options": "User",
			"width": 140,
		},
		{"label": "Law", "fieldname": "law_reference", "fieldtype": "Data", "width": 180},
	]
	data = frappe.get_all("Compliance Obligation", fields=[c["fieldname"] for c in columns], limit=500)
	return columns, data

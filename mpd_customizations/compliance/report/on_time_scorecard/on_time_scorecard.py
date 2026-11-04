import frappe


def execute(filters=None):
	columns = [
		{"label": "Company", "fieldname": "company", "fieldtype": "Data", "width": 180},
		{"label": "Domain", "fieldname": "domain", "fieldtype": "Data", "width": 180},
		{"label": "Completed", "fieldname": "completed", "fieldtype": "Int", "width": 100},
		{"label": "On Time", "fieldname": "on_time", "fieldtype": "Int", "width": 100},
		{"label": "On Time %", "fieldname": "percent", "fieldtype": "Float", "width": 100},
	]
	rows = frappe.get_all(
		"Compliance Activity",
		filters={"status": "Completed"},
		fields=["company", "domain", "days_late"],
	)
	grouped = {}
	for row in rows:
		key = (row.company or "Group", row.domain or "")
		bucket = grouped.setdefault(key, {"completed": 0, "on_time": 0})
		bucket["completed"] += 1
		if not row.days_late:
			bucket["on_time"] += 1
	data = []
	for (company, domain), bucket in sorted(grouped.items()):
		data.append(
			{
				"company": company,
				"domain": domain,
				"completed": bucket["completed"],
				"on_time": bucket["on_time"],
				"percent": round(100 * bucket["on_time"] / bucket["completed"], 1),
			}
		)
	return columns, data

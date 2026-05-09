import frappe
from frappe.utils import today, getdate


def execute(filters=None):
	filters = filters or {}
	columns = _get_columns()
	data = _get_data(filters)
	return columns, data


def _get_columns():
	return [
		{"fieldname": "item", "label": "Item", "fieldtype": "Link", "options": "Item", "width": 150},
		{"fieldname": "item_name", "label": "Item Name", "fieldtype": "Data", "width": 180},
		{"fieldname": "city", "label": "City", "fieldtype": "Link", "options": "City", "width": 100},
		{"fieldname": "supplier", "label": "Supplier", "fieldtype": "Link", "options": "Supplier", "width": 150},
		{"fieldname": "rate_type", "label": "Rate Type", "fieldtype": "Data", "width": 130},
		{"fieldname": "ex_works_rate", "label": "Ex-Works Rate", "fieldtype": "Currency", "width": 110},
		{"fieldname": "freight_per_unit", "label": "Freight/Unit", "fieldtype": "Currency", "width": 100},
		{"fieldname": "delivered_rate", "label": "Delivered Rate", "fieldtype": "Currency", "width": 120},
		{"fieldname": "credit_days", "label": "Credit Days", "fieldtype": "Int", "width": 90},
		{"fieldname": "lead_time_days", "label": "Lead Time", "fieldtype": "Int", "width": 80},
		{"fieldname": "valid_from", "label": "Valid From", "fieldtype": "Datetime", "width": 140},
		{"fieldname": "valid_to", "label": "Valid To", "fieldtype": "Datetime", "width": 140},
		{"fieldname": "status", "label": "Status", "fieldtype": "Data", "width": 90},
		{"fieldname": "name", "label": "Document", "fieldtype": "Link", "options": "Material Rate", "width": 140},
	]


def _get_data(filters):
	db_filters = {}

	if filters.get("item"):
		db_filters["item"] = filters["item"]
	if filters.get("city"):
		db_filters["city"] = filters["city"]
	if filters.get("supplier"):
		db_filters["supplier"] = filters["supplier"]
	if filters.get("from_date"):
		db_filters["valid_from"] = [">=", filters["from_date"]]
	if filters.get("to_date"):
		if "valid_from" in db_filters:
			pass  # single filter; use get_all with multiple filters
		db_filters["valid_to"] = ["<=", filters["to_date"]]

	records = frappe.get_all(
		"Material Rate",
		filters=db_filters,
		fields=[
			"name", "item", "item_name", "city", "supplier", "rate_type",
			"ex_works_rate", "freight_per_unit", "delivered_rate",
			"credit_days", "lead_time_days", "valid_from", "valid_to",
			"docstatus",
		],
		order_by="valid_from desc",
	)

	today_dt = getdate(today())
	result = []
	for r in records:
		if r.docstatus == 0:
			status = "Pending"
		elif r.docstatus == 2:
			status = "Cancelled"
		elif r.valid_to is None or getdate(r.valid_to) >= today_dt:
			status = "Current"
		else:
			status = "Expired"

		# Apply status filter
		status_filter = filters.get("status")
		if status_filter and status_filter != "All" and status != status_filter:
			continue

		row = dict(r)
		row["status"] = status
		result.append(row)

	return result


def get_filters():
	return [
		{
			"fieldname": "item",
			"label": "Item",
			"fieldtype": "Link",
			"options": "Item",
			"reqd": 1,
		},
		{
			"fieldname": "city",
			"label": "City",
			"fieldtype": "Link",
			"options": "City",
		},
		{
			"fieldname": "supplier",
			"label": "Supplier",
			"fieldtype": "Link",
			"options": "Supplier",
		},
		{
			"fieldname": "status",
			"label": "Status",
			"fieldtype": "Select",
			"options": "\nAll\nCurrent\nExpired\nPending\nCancelled",
		},
		{
			"fieldname": "from_date",
			"label": "From Date",
			"fieldtype": "Date",
		},
		{
			"fieldname": "to_date",
			"label": "To Date",
			"fieldtype": "Date",
		},
	]

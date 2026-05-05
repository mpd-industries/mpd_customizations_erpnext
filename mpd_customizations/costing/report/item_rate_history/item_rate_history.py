import frappe

def execute(filters=None):
    columns = [
        {"fieldname": "item", "label": "Item", "fieldtype": "Link", "options": "Item", "width": 150},
        {"fieldname": "city", "label": "City", "fieldtype": "Link", "options": "City", "width": 120},
        {"fieldname": "supplier", "label": "Supplier", "fieldtype": "Link", "options": "Supplier", "width": 150},
        {"fieldname": "rate_type", "label": "Rate Type", "fieldtype": "Data", "width": 120},
        {"fieldname": "ex_works_rate", "label": "Ex-Works Rate (₹)", "fieldtype": "Currency", "width": 120},
        {"fieldname": "freight_per_unit", "label": "Freight/Unit (₹)", "fieldtype": "Currency", "width": 120},
        {"fieldname": "delivered_rate", "label": "Delivered Rate (₹)", "fieldtype": "Currency", "width": 120},
        {"fieldname": "valid_from", "label": "Valid From", "fieldtype": "Datetime", "width": 150},
        {"fieldname": "valid_to", "label": "Valid To", "fieldtype": "Datetime", "width": 150},
        {"fieldname": "is_active", "label": "Active", "fieldtype": "Check", "width": 80},
    ]

    conditions = []
    if filters.get("item"):
        conditions.append("item = %(item)s")
    if filters.get("supplier"):
        conditions.append("supplier = %(supplier)s")
    if filters.get("city"):
        conditions.append("city = %(city)s")

    where_clause = " AND ".join(conditions)
    if where_clause:
        where_clause = "WHERE " + where_clause

    data = frappe.db.sql(f"""
        SELECT
            item, city, supplier, rate_type, ex_works_rate, freight_per_unit,
            delivered_rate, valid_from, valid_to, is_active
        FROM `tabMaterial Rate`
        {where_clause}
        ORDER BY item, city, valid_from DESC
    """, filters, as_dict=1)

    chart = get_chart_data(data)

    return columns, data, None, chart

def get_chart_data(data):
    if not data:
        return None

    dates = []
    rates = []
    
    sorted_data = sorted(data, key=lambda x: x.valid_from)
    
    for d in sorted_data:
        dates.append(d.valid_from.strftime('%Y-%m-%d') if d.valid_from else "")
        rates.append(d.delivered_rate)
        
    return {
        "data": {
            "labels": dates,
            "datasets": [
                {
                    "name": "Delivered Rate",
                    "values": rates
                }
            ]
        },
        "type": "line"
    }

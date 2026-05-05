frappe.query_reports["Item Rate History"] = {
    "filters": [
        {
            "fieldname": "item",
            "label": __("Item"),
            "fieldtype": "Link",
            "options": "Item"
        },
        {
            "fieldname": "supplier",
            "label": __("Supplier"),
            "fieldtype": "Link",
            "options": "Supplier"
        },
        {
            "fieldname": "city",
            "label": __("City"),
            "fieldtype": "Link",
            "options": "City"
        }
    ]
};

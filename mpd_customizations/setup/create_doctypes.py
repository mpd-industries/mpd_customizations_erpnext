import frappe

def create_doctypes():
    # Material Rate
    mr = frappe.get_doc({
        "doctype": "DocType",
        "name": "Material Rate",
        "module": "Costing",
        "custom": 0,
        "is_submittable": 0,
        "track_changes": 1,
        "autoname": "MR-.YYYY.-.#####",
        "fields": [
            {"fieldname": "item", "fieldtype": "Link", "options": "Item", "label": "Item", "reqd": 1, "in_list_view": 1},
            {"fieldname": "item_name", "fieldtype": "Data", "label": "Item Name", "read_only": 1, "fetch_from": "item.item_name"},
            {"fieldname": "supplier", "fieldtype": "Link", "options": "Supplier", "label": "Supplier"},
            {"fieldname": "city", "fieldtype": "Link", "options": "City", "label": "City", "reqd": 1, "in_list_view": 1},
            {"fieldname": "costing_request", "fieldtype": "Link", "options": "Costing Request", "label": "Costing Request"},
            {"fieldname": "section_break_rate", "fieldtype": "Section Break", "label": "Rate"},
            {"fieldname": "rate_type", "fieldtype": "Select", "label": "Rate Type", "reqd": 1, "options": "Ex-Works + Freight\nAll-In Delivered"},
            {"fieldname": "ex_works_rate", "fieldtype": "Currency", "label": "Ex-Works Rate (₹)", "depends_on": "eval:doc.rate_type=='Ex-Works + Freight'"},
            {"fieldname": "freight_per_unit", "fieldtype": "Currency", "label": "Freight per Unit (₹)", "depends_on": "eval:doc.rate_type=='Ex-Works + Freight'"},
            {"fieldname": "delivered_rate", "fieldtype": "Currency", "label": "Delivered Rate (₹)"},
            {"fieldname": "uom", "fieldtype": "Link", "options": "UOM", "label": "UOM", "reqd": 1},
            {"fieldname": "col_break_rate", "fieldtype": "Column Break"},
            {"fieldname": "credit_days", "fieldtype": "Int", "label": "Supplier Credit Days", "default": "0"},
            {"fieldname": "lead_time_days", "fieldtype": "Int", "label": "Lead Time Days"},
            {"fieldname": "section_break_validity", "fieldtype": "Section Break", "label": "Validity"},
            {"fieldname": "valid_from", "fieldtype": "Datetime", "label": "Valid From", "reqd": 1},
            {"fieldname": "valid_to", "fieldtype": "Datetime", "label": "Valid To"},
            {"fieldname": "col_break_validity", "fieldtype": "Column Break"},
            {"fieldname": "is_active", "fieldtype": "Check", "label": "Active", "default": "0"},
            {"fieldname": "notes", "fieldtype": "Small Text", "label": "Notes"}
        ],
        "permissions": [
            {"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1},
            {"role": "Rate Manager", "read": 1, "write": 1, "create": 1, "delete": 1},
            {"role": "Costing User", "read": 1},
            {"role": "Costing Approver", "read": 1}
        ]
    })
    if not frappe.db.exists("DocType", "Material Rate"):
        mr.insert(ignore_permissions=True)

    # Processing Charge
    pc = frappe.get_doc({
        "doctype": "DocType",
        "name": "Processing Charge",
        "module": "Costing",
        "custom": 0,
        "is_submittable": 0,
        "track_changes": 1,
        "autoname": "PC-.YYYY.-.#####",
        "fields": [
            {"fieldname": "processor", "fieldtype": "Link", "options": "Processor", "label": "Processor", "reqd": 1, "in_list_view": 1},
            {"fieldname": "item", "fieldtype": "Link", "options": "Item", "label": "Item (Specific)"},
            {"fieldname": "item_name", "fieldtype": "Data", "label": "Item Name", "read_only": 1, "fetch_from": "item.item_name"},
            {"fieldname": "item_group", "fieldtype": "Link", "options": "Item Group", "label": "Item Group (Fallback)"},
            {"fieldname": "col_break_1", "fieldtype": "Column Break"},
            {"fieldname": "charge_per_kg", "fieldtype": "Currency", "label": "Charge per kg of Solids (₹)", "reqd": 1, "in_list_view": 1},
            {"fieldname": "includes_outward_freight", "fieldtype": "Check", "label": "Includes Outward Freight", "default": "0"},
            {"fieldname": "fg_freight_per_unit", "fieldtype": "Currency", "label": "FG Freight per Unit (₹)", "depends_on": "eval:!doc.includes_outward_freight"},
            {"fieldname": "section_break_validity", "fieldtype": "Section Break", "label": "Validity"},
            {"fieldname": "valid_from", "fieldtype": "Datetime", "label": "Valid From", "reqd": 1},
            {"fieldname": "valid_to", "fieldtype": "Datetime", "label": "Valid To"},
            {"fieldname": "col_break_validity", "fieldtype": "Column Break"},
            {"fieldname": "is_active", "fieldtype": "Check", "label": "Active", "default": "1"},
            {"fieldname": "notes", "fieldtype": "Small Text", "label": "Notes"}
        ],
        "permissions": [
            {"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1},
            {"role": "Rate Manager", "read": 1, "write": 1, "create": 1, "delete": 1},
            {"role": "Costing User", "read": 1},
            {"role": "Costing Approver", "read": 1}
        ]
    })
    if not frappe.db.exists("DocType", "Processing Charge"):
        pc.insert(ignore_permissions=True)

    # Costing Configuration
    cc = frappe.get_doc({
        "doctype": "DocType",
        "name": "Costing Configuration",
        "module": "Costing",
        "custom": 0,
        "issingle": 1,
        "fields": [
            {"fieldname": "engine_version", "fieldtype": "Data", "label": "Engine Version", "default": "1.0.0"},
            {"fieldname": "section_break_production", "fieldtype": "Section Break", "label": "Production Parameters"},
            {"fieldname": "production_days", "fieldtype": "Int", "label": "Production Days", "default": "30"},
            {"fieldname": "section_break_rates", "fieldtype": "Section Break", "label": "Interest Rates"},
            {"fieldname": "supplier_financing_rate_pct", "fieldtype": "Float", "label": "Supplier Financing Rate % pa", "default": "12"},
            {"fieldname": "actual_cost_of_capital_pct", "fieldtype": "Float", "label": "Actual Cost of Capital % pa", "default": "9", "permlevel": 1},
            {"fieldname": "section_break_formulation", "fieldtype": "Section Break", "label": "Formulation Selection"},
            {"fieldname": "auto_exclusion_threshold_pct", "fieldtype": "Float", "label": "Auto Exclusion Threshold %", "default": "15"},
            {"fieldname": "formulation_switch_threshold_pct", "fieldtype": "Float", "label": "Formulation Switch Alert Threshold %", "default": "5"},
            {"fieldname": "section_break_validity", "fieldtype": "Section Break", "label": "Rate Validity"},
            {"fieldname": "default_valid_to", "fieldtype": "Select", "label": "Default Valid To", "options": "End of Month\nEnd of Quarter\nCustom Days", "default": "End of Month"},
            {"fieldname": "default_valid_to_days", "fieldtype": "Int", "label": "Default Valid To Days", "default": "30", "depends_on": "eval:doc.default_valid_to=='Custom Days'"},
            {"fieldname": "rate_expiry_warning_days", "fieldtype": "Int", "label": "Rate Expiry Warning Days", "default": "30"}
        ],
        "permissions": [
            {"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1},
            {"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1, "permlevel": 1},
            {"role": "Costing User", "read": 1},
            {"role": "Costing Approver", "read": 1},
            {"role": "Rate Manager", "read": 1}
        ]
    })
    if not frappe.db.exists("DocType", "Costing Configuration"):
        cc.insert(ignore_permissions=True)


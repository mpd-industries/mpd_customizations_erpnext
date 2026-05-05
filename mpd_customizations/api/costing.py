import frappe
from mpd_customizations.costing.services.config import get_config
from mpd_customizations.costing.services.rate_source_registry import get_default_registry
from mpd_customizations.costing.services.costing_engine import CostingEngine

@frappe.whitelist()
def evaluate_costing(request_name: str, trigger: str = "manual"):
    try:
        config = get_config()
        registry = get_default_registry()
        engine = CostingEngine(registry, config)
        
        result = engine.evaluate(request_name, trigger=trigger)
        
        return {
            "status": "success",
            "message": "Evaluation completed.",
            "data": result
        }
    except Exception as e:
        frappe.log_error("Costing Engine Error", str(e))
        raise

@frappe.whitelist()
def create_pending_rates(request_name):
    # 1. Get all combinations for this request
    combinations = frappe.get_all("Costing Combination", filters={"costing_request": request_name}, pluck="name")
    if not combinations:
        return {"status": "error", "message": "No evaluated combinations found."}
    
    # 2. Get all material lines with missing rates
    missing_lines = frappe.get_all("Costing Material Line", 
        filters={
            "parent": ["in", combinations],
            "rate_freshness": "Missing"
        },
        fields=["item", "city", "uom"]
    )
    
    if not missing_lines:
        return {"status": "success", "message": "No missing rates found."}
    
    # 3. Create pending Material Rate records (unique by item + city)
    created_count = 0
    seen = set()
    for line in missing_lines:
        key = (line.item, line.city)
        if key in seen:
            continue
            
        # Check if a pending rate already exists for this request
        if not frappe.db.exists("Material Rate", {
            "item": line.item,
            "city": line.city,
            "costing_request": request_name,
            "is_active": 0
        }):
            mr = frappe.get_doc({
                "doctype": "Material Rate",
                "item": line.item,
                "city": line.city,
                "uom": line.uom,
                "costing_request": request_name,
                "is_active": 0,
                "rate_type": "All-In Delivered",
                "valid_from": frappe.utils.now_datetime()
            })
            mr.insert(ignore_permissions=True)
            created_count += 1
            
        seen.add(key)
        
    return {
        "status": "success",
        "message": f"Created {created_count} pending rate records.",
        "count": created_count
    }

def on_material_rate_created(doc, method=None):
    """
    Called via doc_events hook.
    Checks if doc.item and doc.city appear in any Costing Material Line for an open Costing Request with rate_freshness = "Missing".
    If found: creates a Frappe notification to the owner of that Costing Request.
    """
    if not doc.is_active:
        return

    # Find combinations that are indicative due to missing rates for this item/city
    requests = frappe.db.sql("""
        SELECT DISTINCT cr.name, cr.owner
        FROM `tabCosting Request` cr
        JOIN `tabCosting Combination` cc ON cc.costing_request = cr.name
        JOIN `tabCosting Material Line` cml ON cml.parent = cc.name
        WHERE cml.item = %s AND cml.city = %s AND cml.rate_freshness = 'Missing'
          AND cr.docstatus = 0
    """, (doc.item, doc.city), as_dict=True)

    for r in requests:
        frappe.publish_realtime("msgprint", {
            "message": f"A rate has been entered for {doc.item} in {doc.city}. Your costing {r.name} may now be evaluatable.",
            "indicator": "green"
        }, user=r.owner)

import frappe
from typing import Dict
from collections import defaultdict
from frappe.utils.data import get_datetime, now_datetime
from mpd_customizations.costing.services.config import CostingConfig
from mpd_customizations.costing.services.rate_source_registry import RateSourceRegistry
from mpd_customizations.costing.services.formulation_selector import FormulationSelector
from mpd_customizations.costing.services.cost_calculator import (
    compute_rm_line_amount,
    compute_financing_cost_for_line,
    compute_processing_cost,
    compute_additional_charge_amount,
    compute_total_cost
)

class CostingEngine:
    def __init__(self, registry: RateSourceRegistry, config: CostingConfig):
        self._registry = registry
        self._config = config

    def evaluate(self, costing_request_name: str, trigger: str = "manual") -> Dict:
        cr = frappe.get_doc("Costing Request", costing_request_name)
        
        # 1. Validate
        if not cr.item or not cr.processor or cr.solids_content_pct is None or not cr.production_days or cr.supplier_financing_rate_pct is None:
            frappe.throw("Costing Request is missing required fields for evaluation.")
            
        if cr.solids_content_pct <= 0 or cr.solids_content_pct >= 100:
            frappe.throw("Solids Content % must be between 0 and 100 exclusive.")

        # 2. Fetch processor city
        processor_city = frappe.db.get_value("Processor", cr.processor, "city")
        if not processor_city:
            frappe.throw("Processor has no city defined.")

        # 3. Fetch active submitted BOMs
        boms = frappe.get_all("BOM", filters={"item": cr.item}, fields=["name", "quantity", "custom_formulation_id"])
        if not boms:
            frappe.throw("No active submitted BOMs found for this item.")

        bom_names = [b.name for b in boms]

        # 4. Fetch BOM items
        bom_items = frappe.get_all("BOM Item", filters={"parent": ["in", bom_names]}, fields=["parent", "item_code", "item_name", "qty", "uom"])
        bom_items_map = defaultdict(list)
        for bi in bom_items:
            bom_items_map[bi.parent].append(bi)

        # 5. Collect unique (item, city) pairs
        pairs = set()
        for bi in bom_items:
            pairs.add((bi.item_code, processor_city))
        pairs_list = list(pairs)

        # 6. Fetch Processing Charge
        now_dt = now_datetime().strftime("%Y-%m-%d %H:%M:%S")
        pc_records = frappe.get_all(
            "Processing Charge",
            filters={
                "processor": cr.processor,
                "item": cr.item,
                "is_active": 1,
                "valid_from": ["<=", now_dt],
            },
            fields=["name", "charge_per_kg", "includes_outward_freight", "fg_freight_per_unit", "valid_to"]
        )
        valid_pc = None
        for p in pc_records:
            if not p.valid_to or get_datetime(p.valid_to) >= now_datetime():
                valid_pc = p
                break
                
        if not valid_pc:
            item_group = frappe.db.get_value("Item", cr.item, "item_group")
            pc_records_group = frappe.get_all(
                "Processing Charge",
                filters={
                    "processor": cr.processor,
                    "item_group": item_group,
                    "is_active": 1,
                    "valid_from": ["<=", now_dt],
                },
                fields=["name", "charge_per_kg", "includes_outward_freight", "fg_freight_per_unit", "valid_to"]
            )
            for p in pc_records_group:
                if not p.valid_to or get_datetime(p.valid_to) >= now_datetime():
                    valid_pc = p
                    break

        # 7. Batch resolve rates
        resolved_rates = self._registry.batch_resolve(pairs_list, now_datetime())

        # 8. Compute for each BOM
        all_combination_results = []
        for bom in boms:
            comb_res = {
                "bom": bom.name,
                "formulation_id": bom.custom_formulation_id,
                "processing_charge_ref": valid_pc.name if valid_pc else None,
                "material_lines": []
            }
            
            rm_cost_per_kg = 0.0
            financing_cost_per_kg = 0.0
            
            has_missing = False
            has_expired = False
            missing_items = []
            expired_items = []
            
            items_in_bom = bom_items_map.get(bom.name, [])
            for bi in items_in_bom:
                qty_per_kg = bi.qty / (bom.quantity or 1.0)
                rate_option = resolved_rates.get((bi.item_code, processor_city))
                
                if not rate_option:
                    continue
                    
                effective_rate = rate_option.delivered_rate
                amount_per_kg = compute_rm_line_amount(qty_per_kg, effective_rate)
                net_financed_days = max(0, int(cr.production_days) - int(rate_option.supplier_credit_days))
                line_financing = compute_financing_cost_for_line(
                    amount_per_kg, cr.production_days, rate_option.supplier_credit_days, cr.supplier_financing_rate_pct
                )
                
                rm_cost_per_kg += amount_per_kg
                financing_cost_per_kg += line_financing
                
                if rate_option.rate_freshness == "Missing":
                    has_missing = True
                    missing_items.append(bi.item_code)
                elif rate_option.rate_freshness == "Expired":
                    has_expired = True
                    expired_items.append(bi.item_code)
                    
                comb_res["material_lines"].append({
                    "item": bi.item_code,
                    "item_name": bi.item_name,
                    "uom": bi.uom,
                    "qty_per_kg_output": qty_per_kg,
                    "supplier": rate_option.supplier,
                    "city": processor_city,
                    "rate_source_ref": rate_option.rate_source_ref,
                    "rate_freshness": rate_option.rate_freshness,
                    "supplier_credit_days": rate_option.supplier_credit_days,
                    "lead_time_days": rate_option.lead_time_days,
                    "delivered_rate": rate_option.delivered_rate,
                    "net_financed_days": net_financed_days,
                    "financing_cost_per_kg": line_financing,
                    "amount_per_kg": amount_per_kg,
                    "confidence_score": rate_option.confidence_score,
                    "is_overridden": 0,
                    "original_rate": effective_rate,
                    "effective_rate": effective_rate
                })
                
            if valid_pc:
                processing_cost_per_kg = compute_processing_cost(cr.solids_content_pct, valid_pc.charge_per_kg)
                outward_freight_per_kg = 0.0 if valid_pc.includes_outward_freight else (valid_pc.fg_freight_per_unit or 0.0)
            else:
                processing_cost_per_kg = 0.0
                outward_freight_per_kg = 0.0
                
            additional_charges_per_kg = sum(
                compute_additional_charge_amount(line.rate, line.basis, cr.solids_content_pct)
                for line in cr.get("additional_charges", [])
            )
            
            total_cost_per_kg = compute_total_cost(
                rm_cost_per_kg, financing_cost_per_kg, processing_cost_per_kg, additional_charges_per_kg, outward_freight_per_kg
            )
            
            status = "Ready to Quote"
            if has_missing or not valid_pc:
                status = "Indicative — Rates Missing"
            elif has_expired:
                status = "Indicative — Rates Expired"
                
            comb_res.update({
                "rm_cost_per_kg": rm_cost_per_kg,
                "financing_cost_per_kg": financing_cost_per_kg,
                "processing_cost_per_kg": processing_cost_per_kg,
                "additional_charges_per_kg": additional_charges_per_kg,
                "outward_freight_per_kg": outward_freight_per_kg,
                "total_cost_per_kg": total_cost_per_kg,
                "status": status,
                "missing_items": ", ".join(missing_items) if missing_items else "",
                "expired_items": ", ".join(expired_items) if expired_items else ""
            })
            all_combination_results.append(comb_res)

        # 9. Run FormulationSelector
        selector_res = FormulationSelector(self._config).select(all_combination_results, cr.preferred_bom)
        
        # 10. Purge old data
        old_combinations = frappe.get_all("Costing Combination", filters={"costing_request": costing_request_name}, pluck="name")
        if old_combinations:
            frappe.db.delete("Costing Material Line", {"parent": ["in", old_combinations]})
        frappe.db.delete("Costing Combination", {"costing_request": costing_request_name})
        
        # 11 & 12. Write records
        for c in all_combination_results:
            comb_doc = frappe.get_doc({
                "doctype": "Costing Combination",
                "parent": costing_request_name,
                "parenttype": "Costing Request",
                "parentfield": "combinations",
                "costing_request": costing_request_name,
                "bom": c["bom"],
                "formulation_id": c["formulation_id"],
                "is_preferred": c.get("is_preferred", 0),
                "rm_cost_per_kg": c["rm_cost_per_kg"],
                "financing_cost_per_kg": c["financing_cost_per_kg"],
                "processing_cost_per_kg": c["processing_cost_per_kg"],
                "additional_charges_per_kg": c["additional_charges_per_kg"],
                "outward_freight_per_kg": c["outward_freight_per_kg"],
                "total_cost_per_kg": c["total_cost_per_kg"],
                "rank": c.get("rank"),
                "delta_pct": c.get("delta_pct"),
                "status": c.get("status"),
                "is_selected": 0,
                "processing_charge_ref": c["processing_charge_ref"],
                "missing_items": c["missing_items"],
                "expired_items": c["expired_items"],
                "evaluated_on": now_datetime()
            })
            
            for ml in c.get("material_lines", []):
                comb_doc.append("material_lines", ml)
            
            comb_doc.insert(ignore_permissions=True)
                
        # 13. Update Costing Request state
        any_ready = any(c["status"] == "Ready to Quote" for c in all_combination_results)
        any_indicative = any(c["status"].startswith("Indicative") for c in all_combination_results)
        
        if any_ready:
            new_mode = "Ready to Quote"
        elif any_indicative:
            new_mode = "Partially Costed"
        else:
            new_mode = "Awaiting Rates"
            
        frappe.db.set_value("Costing Request", costing_request_name, {
            "last_evaluated_on": now_datetime(),
            "engine_version_used": self._config.engine_version,
            "formulation_switch_alert": selector_res.get("switch_alert") or "",
            "mode": new_mode
        })
        
        breakdown = {
            # Layer 1 Data
        }
        
        return {
            "combinations": all_combination_results,
            "breakdown": breakdown,
            "mode": new_mode,
            "switch_alert": selector_res.get("switch_alert")
        }

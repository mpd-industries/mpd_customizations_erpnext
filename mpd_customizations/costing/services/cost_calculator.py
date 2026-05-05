from typing import List, Dict

def compute_rm_line_amount(qty_per_kg_output: float, effective_rate: float) -> float:
    """qty_per_kg_output × effective_rate"""
    return float(qty_per_kg_output) * float(effective_rate)

def compute_financing_cost_for_line(amount_per_kg: float, production_days: int, supplier_credit_days: int, financing_rate_pct: float) -> float:
    """amount_per_kg × (net_financed_days / 365) × (financing_rate_pct / 100)"""
    net_financed_days = max(0, int(production_days) - int(supplier_credit_days))
    return float(amount_per_kg) * (net_financed_days / 365.0) * (float(financing_rate_pct) / 100.0)

def compute_processing_cost(solids_content_pct: float, charge_per_kg: float) -> float:
    """(solids_content_pct / 100) × charge_per_kg"""
    return (float(solids_content_pct) / 100.0) * float(charge_per_kg)

def compute_additional_charge_amount(rate: float, basis: str, solids_content_pct: float) -> float:
    """
    Per kg of Output: rate
    Per kg of Solids: rate × (solids_content_pct / 100)
    """
    if basis == "Per kg of Output":
        return float(rate)
    elif basis == "Per kg of Solids":
        return float(rate) * (float(solids_content_pct) / 100.0)
    raise ValueError(f"Unrecognised basis: {basis}")

def compute_total_cost(rm_cost: float, financing_cost: float, processing_cost: float, additional_charges: float, outward_freight: float) -> float:
    """Sum of all components"""
    return float(rm_cost) + float(financing_cost) + float(processing_cost) + float(additional_charges) + float(outward_freight)

def compute_internal_earnings(material_lines: List[Dict], total_cost_per_kg: float, actual_cost_of_capital_pct: float, supplier_financing_rate_pct: float) -> Dict:
    """RM financing spread per line: amount_per_kg × (net_financed_days / 365) × spread_pct"""
    spread_pct = max(0.0, float(supplier_financing_rate_pct) - float(actual_cost_of_capital_pct))
    
    total_spread = 0.0
    breakdown = []
    
    for line in material_lines:
        amount = float(line.get("amount_per_kg", 0.0))
        net_days = max(0, int(line.get("production_days", 0)) - int(line.get("supplier_credit_days", 0)))
        spread = amount * (net_days / 365.0) * (spread_pct / 100.0)
        
        total_spread += spread
        breakdown.append({
            "item_name": line.get("item_name"),
            "amount_per_kg": amount,
            "net_financed_days": net_days,
            "spread_per_kg": spread
        })
        
    return {
        "rm_spread_per_kg": total_spread,
        "rm_spread_breakdown": breakdown,
        "total_spread_per_kg": total_spread
    }

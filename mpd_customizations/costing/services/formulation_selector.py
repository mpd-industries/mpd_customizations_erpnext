from typing import List, Dict, Tuple
from mpd_customizations.costing.services.config import CostingConfig

class FormulationSelector:
    def __init__(self, config: CostingConfig):
        self.config = config

    def select(self, combinations: List[Dict], preferred_bom: str) -> Dict:
        if not combinations:
            return {"included": [], "excluded": [], "cheapest_cost": 0, "threshold_applied": self.config.auto_exclusion_threshold_pct, "switch_alert": None}

        min_cost = min(c.get("total_cost_per_kg", 0) for c in combinations)

        included = []
        excluded = []
        
        for c in combinations:
            cost = c.get("total_cost_per_kg", 0)
            if min_cost > 0:
                delta_pct = ((cost - min_cost) / min_cost) * 100.0
            else:
                delta_pct = 0.0
                
            c["delta_pct"] = delta_pct
            c["is_preferred"] = (c.get("bom") == preferred_bom)

            if delta_pct > self.config.auto_exclusion_threshold_pct:
                c["status"] = "Excluded — Too Expensive"
                c["rank"] = None
                excluded.append(c)
            else:
                included.append(c)

        included.sort(key=lambda x: x.get("total_cost_per_kg", 0))
        for idx, c in enumerate(included):
            c["rank"] = idx + 1

        switch_alert = None
        if included:
            rank1 = included[0]
            preferred = next((c for c in combinations if c.get("is_preferred")), None)
            
            if preferred and preferred.get("rank") != 1:
                pref_cost = preferred.get("total_cost_per_kg", 0)
                r1_cost = rank1.get("total_cost_per_kg", 0)
                if r1_cost > 0:
                    diff_pct = ((pref_cost - r1_cost) / r1_cost) * 100.0
                    diff_abs = pref_cost - r1_cost
                    if diff_pct > self.config.formulation_switch_threshold_pct:
                        switch_alert = f"Formulation {rank1.get('formulation_id')} costs ₹{diff_abs:.2f}/kg less than your preferred Formulation {preferred.get('formulation_id')} — a {diff_pct:.1f}% difference. Consider switching."

        return {
            "included": included,
            "excluded": excluded,
            "cheapest_cost": min_cost,
            "threshold_applied": self.config.auto_exclusion_threshold_pct,
            "switch_alert": switch_alert
        }

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from mpd_customizations.costing.services.config import CostingConfig


@dataclass
class SelectionResult:
	included: List[Dict] = field(default_factory=list)
	excluded: List[Dict] = field(default_factory=list)
	cheapest_cost: float = 0.0
	threshold_applied: float = 0.0
	switch_alert: Optional[str] = None


class FormulationSelector:
	def __init__(self, config: CostingConfig):
		self._config = config

	def select(self, combinations: List[Dict], preferred_bom: Optional[str]) -> SelectionResult:
		if not combinations:
			return SelectionResult()

		min_cost = min(c["total_cost_per_kg"] for c in combinations)
		result = SelectionResult(cheapest_cost=min_cost, threshold_applied=self._config.auto_exclusion_threshold_pct)

		for combo in combinations:
			cost = combo["total_cost_per_kg"]
			delta_pct = ((cost - min_cost) / min_cost * 100) if min_cost > 0 else 0.0
			combo["delta_pct"] = round(delta_pct, 4)
			combo["is_preferred"] = combo.get("bom") == preferred_bom

			if delta_pct > self._config.auto_exclusion_threshold_pct:
				combo["status"] = "Excluded — Too Expensive"
				combo["rank"] = None
				result.excluded.append(combo)
			else:
				result.included.append(combo)

		result.included.sort(key=lambda c: c["total_cost_per_kg"])
		for rank, combo in enumerate(result.included, start=1):
			combo["rank"] = rank

		if preferred_bom and result.included:
			preferred = next((c for c in result.included if c.get("bom") == preferred_bom), None)
			rank1 = result.included[0]
			if (
				preferred
				and preferred is not rank1
				and rank1["total_cost_per_kg"] > 0
			):
				diff_pct = (
					(preferred["total_cost_per_kg"] - rank1["total_cost_per_kg"])
					/ rank1["total_cost_per_kg"]
					* 100
				)
				if diff_pct > self._config.formulation_switch_threshold_pct:
					saving = preferred["total_cost_per_kg"] - rank1["total_cost_per_kg"]
					result.switch_alert = (
						f"{rank1.get('formulation_id') or rank1.get('bom')} costs ₹{saving:.2f}/kg less "
						f"than preferred {preferred.get('formulation_id') or preferred.get('bom')} "
						f"— a {diff_pct:.1f}% difference "
						f"(threshold: {self._config.formulation_switch_threshold_pct}%)"
					)

		return result

from typing import Dict, List


def compute_rm_line_amount(qty_per_kg_output: float, working_rate: float) -> float:
	return qty_per_kg_output * working_rate


def compute_financing_cost_for_line(
	amount_per_kg: float,
	production_days: int,
	working_supplier_credit_days: int,
	supplier_financing_rate_pct: float,
) -> float:
	net_financed_days = max(0, production_days - working_supplier_credit_days)
	return amount_per_kg * (net_financed_days / 365) * (supplier_financing_rate_pct / 100)


def _effective_solids(solids_content_pct: float) -> float:
	# 99% solids is treated as 100% (industry convention for near-pure solids products)
	return 100.0 if solids_content_pct == 99 else solids_content_pct


def compute_processing_cost(solids_content_pct: float, working_charge_per_kg: float) -> float:
	return (_effective_solids(solids_content_pct) / 100) * working_charge_per_kg


def compute_additional_charge_amount(rate: float, basis: str, solids_content_pct: float) -> float:
	if basis == "Per kg of Output":
		return rate
	elif basis == "Per kg of Solids":
		return rate * (_effective_solids(solids_content_pct) / 100)
	raise ValueError(f"Unrecognised basis: {basis!r}")


def compute_equalized_rate(
	working_rate: float,
	credit_days: int,
	financing_rate_pct: float,
	benefit_rate_pct: float = 8.0,
	baseline_credit: int = 60,
) -> float:
	"""Normalize rate to a 60-day credit baseline for fair comparison.
	Suppliers giving <60d: rate adjusted up at financing_rate_pct.
	Suppliers giving >60d: rate adjusted down at benefit_rate_pct."""
	gap = baseline_credit - (credit_days or 0)
	rate = financing_rate_pct if gap > 0 else benefit_rate_pct
	return working_rate + working_rate * (gap / 365) * (rate / 100)


def compute_total_cost(
	rm_cost: float,
	financing_cost: float,
	processing_cost: float,
	additional_charges: float,
	outward_freight: float,
) -> float:
	return rm_cost + financing_cost + processing_cost + additional_charges + outward_freight


def compute_internal_earnings(
	material_lines: List[Dict],
	actual_cost_of_capital_pct: float,
	supplier_financing_rate_pct: float,
) -> Dict:
	spread_pct = max(0.0, supplier_financing_rate_pct - actual_cost_of_capital_pct)
	breakdown = []
	total_spread = 0.0

	for line in material_lines:
		amount = line.get("amount_per_kg", 0.0)
		net_days = line.get("net_financed_days", 0)
		spread = amount * (net_days / 365) * (spread_pct / 100)
		total_spread += spread
		breakdown.append(
			{
				"item": line.get("item"),
				"item_name": line.get("item_name"),
				"amount_per_kg": amount,
				"net_financed_days": net_days,
				"spread_per_kg": spread,
			}
		)

	return {
		"rm_spread_per_kg": total_spread,
		"rm_spread_breakdown": breakdown,
		"total_spread_per_kg": total_spread,
		"spread_pct": spread_pct,
		"supplier_financing_rate_pct": supplier_financing_rate_pct,
		"actual_cost_of_capital_pct": actual_cost_of_capital_pct,
	}

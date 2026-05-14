from typing import Dict, List

_CREDIT_FREE_DAYS = 30


def compute_rm_line_amount(qty_per_kg_output: float, working_rate: float) -> float:
	return qty_per_kg_output * working_rate


def _effective_solids(solids_content_pct: float) -> float:
	# 99% solids is treated as 100% (industry convention for near-pure solids products)
	return 100.0 if solids_content_pct == 99 else solids_content_pct


def compute_processing_cost(solids_content_pct: float, working_charge_per_kg: float) -> float:
	return (_effective_solids(solids_content_pct) / 100) * working_charge_per_kg


def compute_equalized_rate(
	working_rate: float,
	credit_days: int,
	financing_rate_pct: float,
	benefit_rate_pct: float = 8.0,
	baseline_credit: int = 60,
) -> float:
	"""Normalize a supplier rate to the 60-day credit baseline.
	Called by MaterialRate.before_save to store rate_60d_equivalent.
	Suppliers giving <60d credit: rate adjusted up at financing_rate_pct.
	Suppliers giving >60d credit: rate adjusted down at benefit_rate_pct."""
	gap = baseline_credit - (credit_days or 0)
	rate = financing_rate_pct if gap > 0 else benefit_rate_pct
	return working_rate + working_rate * (gap / 365) * (rate / 100)


def compute_additional_charge_amount(rate: float, basis: str, solids_content_pct: float) -> float:
	if basis == "Per kg of Output":
		return rate
	elif basis == "Per kg of Solids":
		return rate * (_effective_solids(solids_content_pct) / 100)
	raise ValueError(f"Unrecognised basis: {basis!r}")




def compute_credit_charge(
	total_cost_per_kg: float,
	credit_days: int,
	customer_credit_rate_pct: float,
) -> float:
	extra_days = max(0, (credit_days or 0) - _CREDIT_FREE_DAYS)
	return total_cost_per_kg * (extra_days / 365) * (customer_credit_rate_pct / 100)


def compute_commission_amount(
	rate: float,
	commission_type: str,
	total_cost_per_kg: float,
	solids_content_pct: float,
) -> float:
	if commission_type == "% of Sale Price":
		if rate >= 100:
			raise ValueError("Margin rate must be less than 100%")
			
		commission_amount = (total_cost_per_kg * rate) / (100 - rate)
		return commission_amount
	elif commission_type == "Per kg of Output":
		return rate
	elif commission_type == "Per kg of Solids":
		return rate * (_effective_solids(solids_content_pct) / 100)
	raise ValueError(f"Unrecognised commission_type: {commission_type!r}")


def compute_total_commission(
	commissions: List[Dict],
	total_cost_per_kg: float,
	solids_content_pct: float,
) -> float:
	return sum(
		compute_commission_amount(
			c.get("rate") or 0,
			c.get("commission_type") or "",
			total_cost_per_kg,
			solids_content_pct,
		)
		for c in commissions
	)


def compute_margin(
	total_cost_per_kg: float,
	margin_type: str,
	margin_rate: float,
	solids_content_pct: float,
) -> float:
	rate = margin_rate or 0
	if margin_type == "% of Sale Price":
    # Prevent division by zero or negative results if rate >= 100
		if rate >= 100:
			raise ValueError("Margin rate must be less than 100%")
			
		commission_amount = (total_cost_per_kg * rate) / (100 - rate)
		return commission_amount
	elif margin_type == "Per kg of Output":
		return rate
	elif margin_type == "Per kg of Solids":
		return rate * (_effective_solids(solids_content_pct) / 100)
	return 0.0


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

import math

import frappe
from frappe.model.document import Document

from mpd_customizations.xfloor_costing.services.pl_constants import (
	COMPONENT_GM_FIELD,
)
from mpd_customizations.xfloor_costing.services.pl_helpers import (
	_cost_per_sqft,
	_f,
)


def _summary_from_totals(contract, total, sqft):
	profit_loss = contract - total
	margin_pct = (profit_loss / contract * 100) if contract else 0
	return {
		"contract_value": contract,
		"total_cost": total,
		"profit_loss": profit_loss,
		"margin_pct": margin_pct,
		"cost_per_sqft": _cost_per_sqft(sqft, total),
	}


def _gm_for_component(cfg, component):
	fieldname = COMPONENT_GM_FIELD.get(component)
	if not fieldname:
		return 0.0
	return _f(cfg.get(fieldname))


def _attach_gm(budget_rows, cfg):
	for row in budget_rows:
		component = row.get("component")
		if component == "Applicator":
			row["gm_per_kit"] = 0
			row["gm_amount"] = 0
			continue
		gm_per_kit = _gm_for_component(cfg, component)
		kits = _f(row.get("kits"))
		row["gm_per_kit"] = gm_per_kit
		row["gm_amount"] = kits * gm_per_kit
	return budget_rows


def _pct(numerator, denominator):
	if not denominator:
		return 0.0
	return numerator / denominator * 100.0


def _applicator_cost(budget_rows):
	for row in budget_rows or []:
		if row.get("component") == "Applicator":
			return _f(row.get("cost"))
	return 0.0


def _kit_spend_total(budget_rows):
	return sum(_f(r.get("cost")) for r in (budget_rows or []) if r.get("component") != "Applicator")


def _margin_rows_from_budget(budget_rows, *, total_kit_gm=None):
	"""Kit components only (no Applicator), with spend + GM profile."""
	raw = []
	for row in budget_rows or []:
		if row.get("component") == "Applicator":
			continue
		kits = _f(row.get("kits"))
		rate = _f(row.get("rate"))
		kit_spend = _f(row.get("cost"))
		gm_per_kit = _f(row.get("gm_per_kit"))
		gm_amount = _f(row.get("gm_amount"))
		raw.append(
			{
				"component": row.get("component"),
				"kits": kits,
				"rate": rate,
				"kit_spend": kit_spend,
				"gm_per_kit": gm_per_kit,
				"gm_amount": gm_amount,
				"gm_pct_of_spend": _pct(gm_amount, kit_spend),
			}
		)
	gm_total = total_kit_gm if total_kit_gm is not None else sum(r["gm_amount"] for r in raw)
	for row in raw:
		row["gm_share_pct"] = _pct(row["gm_amount"], gm_total)
	return raw


def _enrich_part_margin(part):
	rows = _margin_rows_from_budget(part.get("budget_rows"))
	total_kit_gm = sum(r["gm_amount"] for r in rows)
	# Recompute shares against this part's GM total
	rows = _margin_rows_from_budget(part.get("budget_rows"), total_kit_gm=total_kit_gm)
	summary = part.get("summary") or {}
	total_kit_spend = sum(r["kit_spend"] for r in rows)
	contract = _f(summary.get("contract_value"))
	total_cost = _f(summary.get("total_cost"))
	profit_loss = _f(summary.get("profit_loss"))
	margin_pct = _f(summary.get("margin_pct"))
	adjusted_gross_margin = profit_loss + total_kit_gm
	return {
		"part_name": part.get("part_name"),
		"sqft": part.get("sqft"),
		"rows": rows,
		"total_kit_gm": total_kit_gm,
		"total_kit_spend": total_kit_spend,
		"applicator_cost": _applicator_cost(part.get("budget_rows")),
		"contract_value": contract,
		"total_cost": total_cost,
		"profit_loss": profit_loss,
		"margin_pct": margin_pct,
		"adjusted_gross_margin": adjusted_gross_margin,
		"adjusted_gm_pct": _pct(adjusted_gross_margin, contract),
		"gm_pct_of_kit_spend": _pct(total_kit_gm, total_kit_spend),
		"gm_pct_of_contract": _pct(total_kit_gm, contract),
	}


def _build_margin_summary(budget_rows, part_budgets, summary=None):
	summary = summary or {}
	by_component = _margin_rows_from_budget(budget_rows)
	total_kit_gm = sum(r["gm_amount"] for r in by_component)
	by_component = _margin_rows_from_budget(budget_rows, total_kit_gm=total_kit_gm)
	total_kit_spend = sum(r["kit_spend"] for r in by_component)
	contract = _f(summary.get("contract_value"))
	total_cost = _f(summary.get("total_cost"))
	profit_loss = _f(summary.get("profit_loss"))
	margin_pct = _f(summary.get("margin_pct"))
	# Same P&L Cost Profile sees; kit GM is extra money earned → adjusted gross margin.
	adjusted_gross_margin = profit_loss + total_kit_gm
	part_margins = [_enrich_part_margin(part) for part in (part_budgets or [])]
	return {
		"total_kit_gm": total_kit_gm,
		"total_kit_spend": total_kit_spend,
		"applicator_cost": _applicator_cost(budget_rows),
		"contract_value": contract,
		"total_cost": total_cost,
		"profit_loss": profit_loss,
		"margin_pct": margin_pct,
		"adjusted_gross_margin": adjusted_gross_margin,
		"adjusted_gm_pct": _pct(adjusted_gross_margin, contract),
		"gm_pct_of_kit_spend": _pct(total_kit_gm, total_kit_spend),
		"gm_pct_of_contract": _pct(total_kit_gm, contract),
		"by_component": by_component,
		"part_margins": part_margins,
	}


def _cost_rows_from_budget(budget_rows, *, total_cost=None):
	"""All components including Applicator — no GM fields."""
	total = total_cost if total_cost is not None else sum(_f(r.get("cost")) for r in (budget_rows or []))
	rows = []
	for row in budget_rows or []:
		cost = _f(row.get("cost"))
		rows.append(
			{
				"component": row.get("component"),
				"kits": _f(row.get("kits")),
				"rate": _f(row.get("rate")),
				"kit_spend": cost,
				"spend_share_pct": _pct(cost, total),
			}
		)
	return rows


def _enrich_part_cost_profile(part):
	summary = part.get("summary") or {}
	total_cost = _f(summary.get("total_cost"))
	contract = _f(summary.get("contract_value"))
	rows = _cost_rows_from_budget(part.get("budget_rows"), total_cost=total_cost)
	total_kit_spend = _kit_spend_total(part.get("budget_rows"))
	return {
		"part_name": part.get("part_name"),
		"sqft": part.get("sqft"),
		"rows": rows,
		"total_kit_spend": total_kit_spend,
		"applicator_cost": _applicator_cost(part.get("budget_rows")),
		"contract_value": contract,
		"total_cost": total_cost,
		"profit_loss": _f(summary.get("profit_loss")),
		"margin_pct": _f(summary.get("margin_pct")),
		"kit_spend_pct_of_contract": _pct(total_kit_spend, contract),
	}


def _build_cost_profile(budget_rows, part_budgets, summary=None):
	"""Safe for all roles — component spend + project P&L, no kit GM."""
	summary = summary or {}
	contract = _f(summary.get("contract_value"))
	total_cost = _f(summary.get("total_cost"))
	profit_loss = _f(summary.get("profit_loss"))
	margin_pct = _f(summary.get("margin_pct"))
	total_kit_spend = _kit_spend_total(budget_rows)
	return {
		"by_component": _cost_rows_from_budget(budget_rows, total_cost=total_cost),
		"total_kit_spend": total_kit_spend,
		"applicator_cost": _applicator_cost(budget_rows),
		"contract_value": contract,
		"total_cost": total_cost,
		"profit_loss": profit_loss,
		"margin_pct": margin_pct,
		"kit_spend_pct_of_contract": _pct(total_kit_spend, contract),
		"part_profiles": [_enrich_part_cost_profile(part) for part in (part_budgets or [])],
	}

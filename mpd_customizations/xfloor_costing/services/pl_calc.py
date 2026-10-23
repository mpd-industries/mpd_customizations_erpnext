import math

import frappe
from frappe.model.document import Document

from mpd_customizations.xfloor_costing.services.pl_constants import (
	BUDGET_COMPONENTS,
	COMPONENTS,
)
from mpd_customizations.xfloor_costing.services.pl_helpers import (
	_ceil_div,
	_cost_per_sqft,
	_coverage_for,
	_coving_kits_from_feet,
	_f,
	_normalize_component,
	_normalize_project_data,
	get_kit_rates_doc,
)
from mpd_customizations.xfloor_costing.services.pl_profiles import (
	_attach_gm,
	_build_cost_profile,
	_build_margin_summary,
	_summary_from_totals,
)


def calc_part(part_dict, settings, *, rate_per_sqft=None, coving_kits=None, hibuild_kits=None):
	"""Calculate budget for a single area/part. Rates/kits default from the part row.

	Coving is project-level (running feet); part coving kits are always 0 unless explicitly
	passed via coving_kits for legacy flat calc without running feet.
	"""
	cfg = settings
	sqft = _f(part_dict.get("sqft"))
	top_coat_option = part_dict.get("top_coat_option") or "1mm"
	pu_top_coat_option = part_dict.get("pu_top_coat_option") or "0"
	screed_option = part_dict.get("screed_option") or "1mm"
	if "applicator_rate" not in part_dict or part_dict.get("applicator_rate") is None:
		applicator_rate = _f(cfg.get("default_applicator_rate")) or 10.0
	else:
		applicator_rate = _f(part_dict.get("applicator_rate"))

	rate_per_sqft = _f(part_dict.get("rate_per_sqft") if rate_per_sqft is None else rate_per_sqft)
	# Prefer explicit override; otherwise zero part-level coving (project owns it).
	if coving_kits is not None:
		coving_kits = _f(coving_kits)
	else:
		coving_kits = 0.0
	hibuild_kits = _f(part_dict.get("hibuild_kits") if hibuild_kits is None else hibuild_kits)

	tc_cov, sc_cov, pu_cov = _coverage_for(cfg, top_coat_option, screed_option, pu_top_coat_option)
	pr_cov = _f(cfg.get("primer_coverage"))

	tc_kits = _ceil_div(sqft, tc_cov)
	pu_kits = _ceil_div(sqft, pu_cov)
	sc_kits = _ceil_div(sqft, sc_cov)
	pr_kits = _ceil_div(sqft, pr_cov)

	tc_cost = tc_kits * _f(cfg.get("top_coat_rate"))
	pu_cost = pu_kits * _f(cfg.get("pu_top_coat_rate"))
	sc_cost = sc_kits * _f(cfg.get("screed_rate"))
	pr_cost = pr_kits * _f(cfg.get("primer_rate"))
	co_cost = coving_kits * _f(cfg.get("coving_rate"))
	hi_cost = hibuild_kits * _f(cfg.get("hibuild_rate"))
	app_cost = applicator_rate * sqft

	contract = sqft * rate_per_sqft
	total = tc_cost + pu_cost + sc_cost + pr_cost + co_cost + hi_cost + app_cost

	budget_rows = [
		{
			"component": "Epoxy Top coat",
			"option": top_coat_option,
			"coverage": tc_cov,
			"kits": tc_kits,
			"rate": _f(cfg.get("top_coat_rate")),
			"cost": tc_cost,
		},
		{
			"component": "PU Top coat",
			"option": pu_top_coat_option,
			"coverage": pu_cov,
			"kits": pu_kits,
			"rate": _f(cfg.get("pu_top_coat_rate")),
			"cost": pu_cost,
		},
		{
			"component": "Screed",
			"option": screed_option,
			"coverage": sc_cov,
			"kits": sc_kits,
			"rate": _f(cfg.get("screed_rate")),
			"cost": sc_cost,
		},
		{
			"component": "Primer",
			"option": "-",
			"coverage": pr_cov,
			"kits": pr_kits,
			"rate": _f(cfg.get("primer_rate")),
			"cost": pr_cost,
		},
		{
			"component": "Coving",
			"option": "-",
			"coverage": 0,
			"kits": coving_kits,
			"rate": _f(cfg.get("coving_rate")),
			"cost": co_cost,
		},
		{
			"component": "Hi-build",
			"option": "-",
			"coverage": 0,
			"kits": hibuild_kits,
			"rate": _f(cfg.get("hibuild_rate")),
			"cost": hi_cost,
		},
		{
			"component": "Applicator",
			"option": "-",
			"coverage": 0,
			"kits": 0,
			"rate": applicator_rate,
			"cost": app_cost,
		},
	]

	for row in budget_rows:
		row["cost_per_sqft"] = _cost_per_sqft(sqft, row["cost"])

	_attach_gm(budget_rows, cfg)

	return {
		"part_name": part_dict.get("part_name") or "Main",
		"sqft": sqft,
		"rate_per_sqft": rate_per_sqft,
		"summary": _summary_from_totals(contract, total, sqft),
		"budget_rows": budget_rows,
	}


def _part_row_dict(row):
	if isinstance(row, dict):
		return row
	if hasattr(row, "as_dict"):
		return row.as_dict()
	return {
		"part_name": getattr(row, "part_name", None),
		"sqft": getattr(row, "sqft", None),
		"rate_per_sqft": getattr(row, "rate_per_sqft", None),
		"top_coat_option": getattr(row, "top_coat_option", None),
		"pu_top_coat_option": getattr(row, "pu_top_coat_option", None),
		"screed_option": getattr(row, "screed_option", None),
		"coving_kits": getattr(row, "coving_kits", None),
		"hibuild_kits": getattr(row, "hibuild_kits", None),
		"applicator_rate": getattr(row, "applicator_rate", None),
	}


def _normalize_parts(data):
	return [_part_row_dict(row) for row in (data.get("parts") or [])]


def _rollup_budget_rows(part_results, total_sqft, cfg):
	by_component = {name: [] for name in BUDGET_COMPONENTS}
	for part in part_results:
		for row in part["budget_rows"]:
			component = row["component"]
			if component in by_component:
				by_component[component].append(row)

	rolled = []
	for component in BUDGET_COMPONENTS:
		rows = by_component[component]
		options = {r.get("option") for r in rows}
		coverages = {r.get("coverage") for r in rows}
		rates = {r.get("rate") for r in rows}
		kits = sum(_f(r.get("kits")) for r in rows)
		cost = sum(_f(r.get("cost")) for r in rows)

		option = next(iter(options)) if len(options) == 1 else ("mixed" if options else "-")
		coverage = next(iter(coverages)) if len(coverages) == 1 else 0
		rate = next(iter(rates)) if len(rates) == 1 else 0

		rolled.append(
			{
				"component": component,
				"option": option,
				"coverage": coverage,
				"kits": kits,
				"rate": rate,
				"cost": cost,
				"cost_per_sqft": _cost_per_sqft(total_sqft, cost),
			}
		)

	_attach_gm(rolled, cfg)
	return rolled


def _apply_project_coving(budget_rows, coving_kits, cfg, total_sqft):
	"""Replace rolled Coving row with project-level kits from running feet."""
	cov = _f(cfg.get("coving_coverage")) or 150.0
	rate = _f(cfg.get("coving_rate"))
	kits = _f(coving_kits)
	cost = kits * rate
	out = []
	for row in budget_rows or []:
		if row.get("component") != "Coving":
			out.append(row)
			continue
		item = dict(row)
		item["option"] = "-"
		item["coverage"] = cov
		item["kits"] = kits
		item["rate"] = rate
		item["cost"] = cost
		item["cost_per_sqft"] = _cost_per_sqft(total_sqft, cost)
		out.append(item)
	_attach_gm(out, cfg)
	return out


def _legacy_coving_kits(data, parts):
	legacy = _f(data.get("coving_kits"))
	if legacy > 0:
		return legacy
	return sum(_f(p.get("coving_kits")) for p in (parts or []))


def _resolve_project_coving_kits(data, cfg, parts):
	"""Prefer running feet; fall back to project/part kits when feet not entered."""
	feet = data.get("coving_running_feet")
	if _f(feet) > 0:
		return float(_coving_kits_from_feet(feet, cfg.get("coving_coverage")))
	return float(_legacy_coving_kits(data, parts))


def calc_project(doc_or_dict, settings=None):
	data = _normalize_project_data(doc_or_dict)
	cfg = settings or get_kit_rates_doc()
	parts = _normalize_parts(data)
	project_coving = _resolve_project_coving_kits(data, cfg, parts)

	if parts:
		part_results = [calc_part(part, cfg) for part in parts]
		total_sqft = sum(_f(p["sqft"]) for p in part_results)
		budget_rows = _rollup_budget_rows(part_results, total_sqft, cfg)
		budget_rows = _apply_project_coving(budget_rows, project_coving, cfg, total_sqft)
		total_cost = sum(_f(r["cost"]) for r in budget_rows)
		contract = sum(_f(p["summary"]["contract_value"]) for p in part_results)
		part_budgets = [
			{
				"part_name": p["part_name"],
				"sqft": p["sqft"],
				"rate_per_sqft": p["rate_per_sqft"],
				"summary": p["summary"],
				"budget_rows": p["budget_rows"],
			}
			for p in part_results
		]

		summary = _summary_from_totals(contract, total_cost, total_sqft)
		return {
			"summary": summary,
			"budget_rows": budget_rows,
			"part_budgets": part_budgets,
			"coving_kits": project_coving,
			"margin_summary": _build_margin_summary(budget_rows, part_budgets, summary),
			"cost_profile": _build_cost_profile(budget_rows, part_budgets, summary),
		}

	# Legacy flat payload (no parts): apply project coving kits directly.
	legacy_part = {
		"part_name": "Main",
		"sqft": data.get("sqft"),
		"rate_per_sqft": data.get("rate_per_sqft"),
		"top_coat_option": data.get("top_coat_option") or "1mm",
		"pu_top_coat_option": data.get("pu_top_coat_option") or "0",
		"screed_option": data.get("screed_option") or "1mm",
		"hibuild_kits": data.get("hibuild_kits"),
		"applicator_rate": data.get("applicator_rate"),
	}
	result = calc_part(legacy_part, cfg, coving_kits=project_coving)
	# Ensure coverage shown on coving row
	result["budget_rows"] = _apply_project_coving(
		result["budget_rows"], project_coving, cfg, _f(result.get("sqft"))
	)
	summary = _summary_from_totals(
		_f(result["summary"]["contract_value"]),
		sum(_f(r["cost"]) for r in result["budget_rows"]),
		_f(result.get("sqft")),
	)
	return {
		"summary": summary,
		"budget_rows": result["budget_rows"],
		"part_budgets": [],
		"coving_kits": project_coving,
		"margin_summary": _build_margin_summary(result["budget_rows"], [], summary),
		"cost_profile": _build_cost_profile(result["budget_rows"], [], summary),
	}


def flat_fields_to_main_part(data):
	"""Build a Main part dict from legacy flat Floor Project fields."""
	return {
		"part_name": "Main",
		"sqft": _f(data.get("sqft")),
		"rate_per_sqft": _f(data.get("rate_per_sqft")),
		"top_coat_option": data.get("top_coat_option") or "1mm",
		"pu_top_coat_option": data.get("pu_top_coat_option") or "0",
		"screed_option": data.get("screed_option") or "1mm",
		"coving_kits": _f(data.get("coving_kits")),
		"hibuild_kits": _f(data.get("hibuild_kits")),
		"applicator_rate": _f(data.get("applicator_rate")),
	}


def calc_actual_totals(dispatch_lines):
	kits = 0.0
	cost = 0.0
	for row in dispatch_lines or []:
		row_kits = _f(row.get("kits") if isinstance(row, dict) else row.kits)
		row_rate = _f(row.get("rate_per_kit") if isinstance(row, dict) else row.rate_per_kit)
		kits += row_kits
		cost += row_kits * row_rate
	return {"kits": kits, "cost": cost}


def calc_actual_by_component(dispatch_lines):
	result = {name: {"kits": 0.0, "cost": 0.0} for name in COMPONENTS}
	for row in dispatch_lines or []:
		component = _normalize_component(row.get("component") if isinstance(row, dict) else row.component)
		if component not in result:
			continue
		row_kits = _f(row.get("kits") if isinstance(row, dict) else row.kits)
		row_rate = _f(row.get("rate_per_kit") if isinstance(row, dict) else row.rate_per_kit)
		result[component]["kits"] += row_kits
		result[component]["cost"] += row_kits * row_rate
	return result


def build_comparison(budget_rows, dispatch_lines):
	actual = calc_actual_by_component(dispatch_lines)
	comparison = []
	for row in budget_rows:
		component = row.get("component")
		if component == "Applicator":
			continue
		budget_kits = _f(row.get("kits"))
		budget_cost = _f(row.get("cost"))
		actual_row = actual.get(component, {"kits": 0, "cost": 0})
		comparison.append(
			{
				"component": component,
				"budget_kits": budget_kits,
				"actual_kits": actual_row["kits"],
				"budget_cost": budget_cost,
				"actual_cost": actual_row["cost"],
				"variance_cost": budget_cost - actual_row["cost"],
				"variance_kits": budget_kits - actual_row["kits"],
			}
		)
	return comparison

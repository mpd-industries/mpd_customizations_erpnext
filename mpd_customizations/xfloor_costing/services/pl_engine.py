import math

import frappe
from frappe.model.document import Document

COMPONENTS = ("Epoxy Top coat", "PU Top coat", "Screed", "Primer", "Coving", "Hi-build")
BUDGET_COMPONENTS = COMPONENTS + ("Applicator",)

# Legacy dispatch / comparison labels
COMPONENT_ALIASES = {
	"Top coat": "Epoxy Top coat",
}

COMPONENT_GM_FIELD = {
	"Epoxy Top coat": "top_coat_gm",
	"PU Top coat": "pu_top_coat_gm",
	"Screed": "screed_gm",
	"Primer": "primer_gm",
	"Coving": "coving_gm",
	"Hi-build": "hibuild_gm",
}

TOP_COAT_OPTS = ("0", "500 micron", "1mm", "2mm", "3mm", "4mm")
EPOXY_TOP_COAT_OPTS = ("500 micron", "1mm", "2mm", "3mm", "4mm")
PU_TOP_COAT_OPTS = ("1mm", "2mm", "3mm", "4mm")
SCREED_OPTS = ("0", "500 micron", "1mm", "2mm", "3mm", "4mm", "5mm", "6mm", "7mm")
SQFT_PER_SQM = 10.7639

DEFAULT_RATES = {
	"top_coat_rate": 4230,
	"pu_top_coat_rate": 4230,
	"screed_rate": 3580,
	"primer_rate": 2012,
	"hibuild_rate": 1650,
	"coving_rate": 2800,
	"default_applicator_rate": 10,
	"top_coat_gm": 0,
	"pu_top_coat_gm": 0,
	"screed_gm": 0,
	"primer_gm": 0,
	"hibuild_gm": 0,
	"coving_gm": 0,
}

DEFAULT_COVERAGE = {
	"top_coat_500_coverage": 193,
	"top_coat_1mm_coverage": 139,
	"top_coat_2mm_coverage": 107,
	"top_coat_3mm_coverage": 107,
	"top_coat_4mm_coverage": 107,
	"pu_top_coat_1mm_coverage": 139,
	"pu_top_coat_2mm_coverage": 107,
	"pu_top_coat_3mm_coverage": 107,
	"pu_top_coat_4mm_coverage": 107,
	"screed_500_coverage": 150,
	"screed_1mm_coverage": 129,
	"screed_2mm_coverage": 96,
	"screed_3mm_coverage": 96,
	"screed_4mm_coverage": 96,
	"screed_5mm_coverage": 96,
	"screed_6mm_coverage": 96,
	"screed_7mm_coverage": 96,
	"primer_coverage": 750,
	"coving_coverage": 150,
}

GM_FIELDNAMES = (
	"top_coat_gm",
	"pu_top_coat_gm",
	"screed_gm",
	"primer_gm",
	"hibuild_gm",
	"coving_gm",
)


def _f(value):
	try:
		return float(value or 0)
	except (TypeError, ValueError):
		return 0.0


def _ceil_div(numerator, denominator):
	if denominator <= 0:
		return 0
	return int(math.ceil(numerator / denominator))


def _coving_kits_from_feet(feet, coverage):
	"""Coving kits from running feet and coverage (ft/kit)."""
	return _ceil_div(_f(feet), _f(coverage) or 150.0)


def _normalize_component(name):
	return COMPONENT_ALIASES.get(name, name)


def _epoxy_coverage_map(settings):
	return {
		"0": 0,
		"500 micron": _f(settings.get("top_coat_500_coverage")),
		"1mm": _f(settings.get("top_coat_1mm_coverage")),
		"2mm": _f(settings.get("top_coat_2mm_coverage")),
		"3mm": _f(settings.get("top_coat_3mm_coverage")),
		"4mm": _f(settings.get("top_coat_4mm_coverage")),
	}


def _pu_coverage_map(settings):
	return {
		"0": 0,
		"1mm": _f(settings.get("pu_top_coat_1mm_coverage")),
		"2mm": _f(settings.get("pu_top_coat_2mm_coverage")),
		"3mm": _f(settings.get("pu_top_coat_3mm_coverage")),
		"4mm": _f(settings.get("pu_top_coat_4mm_coverage")),
	}


def _screed_coverage_map(settings):
	return {
		"0": 0,
		"500 micron": _f(settings.get("screed_500_coverage")),
		"1mm": _f(settings.get("screed_1mm_coverage")),
		"2mm": _f(settings.get("screed_2mm_coverage")),
		"3mm": _f(settings.get("screed_3mm_coverage")),
		"4mm": _f(settings.get("screed_4mm_coverage")),
		"5mm": _f(settings.get("screed_5mm_coverage")),
		"6mm": _f(settings.get("screed_6mm_coverage")),
		"7mm": _f(settings.get("screed_7mm_coverage")),
	}


def _coverage_for(settings, top_coat_option, screed_option, pu_top_coat_option=None):
	tc_map = _epoxy_coverage_map(settings)
	pu_map = _pu_coverage_map(settings)
	sc_map = _screed_coverage_map(settings)
	epoxy = tc_map.get(top_coat_option, tc_map["1mm"])
	screed = sc_map.get(screed_option, sc_map["1mm"])
	pu = pu_map.get(pu_top_coat_option or "0", 0)
	return epoxy, screed, pu


def get_kit_rates_doc():
	"""Load rates/coverage for costing. Uses DB so GM fields are available for calc even when the session user lacks permlevel 1."""
	values = {}
	for fieldname, fallback in DEFAULT_RATES.items():
		try:
			raw = frappe.db.get_single_value("Kit rates", fieldname)
		except Exception:
			raw = None
		if fieldname in GM_FIELDNAMES:
			values[fieldname] = _f(raw)
		else:
			values[fieldname] = _f(raw) or float(fallback)

	for fieldname, fallback in DEFAULT_COVERAGE.items():
		try:
			raw = frappe.db.get_single_value("Kit Coverage", fieldname)
		except Exception:
			raw = None
		values[fieldname] = _f(raw) or float(fallback)
	return values


def _get_setting_value(doc, fieldname):
	if isinstance(doc, dict):
		return doc.get(fieldname)
	return doc.get(fieldname) if doc else None


def _normalize_project_data(doc_or_dict):
	if isinstance(doc_or_dict, Document):
		return doc_or_dict.as_dict()
	if isinstance(doc_or_dict, dict):
		return dict(doc_or_dict)
	return {}


def _cost_per_sqft(sqft, cost):
	return (cost / sqft) if sqft else 0


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
		component = _normalize_component(
			row.get("component") if isinstance(row, dict) else row.component
		)
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


def _area_rate(kit_rate, coverage):
	cov = _f(coverage)
	if cov <= 0:
		return 0.0, 0.0
	per_sqft = _f(kit_rate) / cov
	return per_sqft, per_sqft * SQFT_PER_SQM


def round_price_list_rate(value):
	"""Price-list / print rounding to nearest ₹0.50 with .25 up / below .25 down.

	Examples: 1.20 → 1, 1.25 → 1.50, 1.37 → 1.50, 1.75 → 2.
	"""
	v = _f(value)
	if abs(v) < 1e-12:
		return 0.0
	sign = 1.0 if v >= 0 else -1.0
	v = abs(v)
	whole = int(math.floor(v + 1e-12))
	frac = v - whole
	if frac < 0.25:
		out = float(whole)
	elif frac < 0.75:
		out = whole + 0.5
	else:
		out = float(whole + 1)
	return sign * out


def format_price_list_rate(value, *, blank_zero=False):
	"""Format rounded price-list rate as always-2dp (.00 or .50 only)."""
	rounded = round_price_list_rate(value)
	if blank_zero and abs(rounded) < 1e-12:
		return ""
	return f"{rounded:.2f}"


def _thickness_label(opt):
	"""Display thickness like the commercial price sheet (0 mm / 500 mic / 1 mm)."""
	if opt in (None, "", "0"):
		return "0 mm"
	if opt == "500 micron":
		return "500 mic"
	if isinstance(opt, str) and opt.endswith("mm") and " " not in opt:
		return f"{opt[:-2]} mm"
	return str(opt)


# Price sheet matrix: include Epoxy 0mm (no top coat); PU starts at 1mm
PRICE_LIST_SCREED_OPTS = ("1mm", "2mm", "3mm", "4mm", "5mm", "6mm", "7mm")
PRICE_LIST_EPOXY_TOP = ("0",) + EPOXY_TOP_COAT_OPTS
PRICE_LIST_PU_TOP = PU_TOP_COAT_OPTS


def build_price_list(settings=None):
	"""Commercial rate sheet: system × primer/screed/top coat/application ₹/sqft."""
	cfg = settings or get_kit_rates_doc()
	epoxy_map = _epoxy_coverage_map(cfg)
	pu_map = _pu_coverage_map(cfg)
	sc_map = _screed_coverage_map(cfg)
	primer_cov = _f(cfg.get("primer_coverage"))
	primer_sqft, primer_sqm = _area_rate(cfg.get("primer_rate"), primer_cov)
	app_rate = _f(cfg.get("default_applicator_rate")) or 10.0

	def _unit_rows(label, rate_field, coverage_map, opts):
		rows = []
		rate = _f(cfg.get(rate_field))
		for opt in opts:
			if opt == "0":
				continue
			cov = coverage_map.get(opt) or 0
			per_sqft, per_sqm = _area_rate(rate, cov)
			rows.append(
				{
					"component": label,
					"option": opt,
					"coverage": cov,
					"rate_per_kit": rate,
					"per_sqft": per_sqft,
					"per_sqm": per_sqm,
				}
			)
		return rows

	epoxy_units = _unit_rows("Epoxy Top coat", "top_coat_rate", epoxy_map, EPOXY_TOP_COAT_OPTS)
	pu_units = _unit_rows("PU Top coat", "pu_top_coat_rate", pu_map, PU_TOP_COAT_OPTS)
	screed_units = _unit_rows("Screed", "screed_rate", sc_map, SCREED_OPTS)

	matrix = []

	def _append_block(system, top_opts, rate_field, coverage_map):
		top_rate = _f(cfg.get(rate_field))
		for top in top_opts:
			top_sqft = 0.0
			if top != "0":
				top_sqft, _ = _area_rate(top_rate, coverage_map.get(top) or 0)
			for sc in PRICE_LIST_SCREED_OPTS:
				sc_sqft, _ = _area_rate(cfg.get("screed_rate"), sc_map.get(sc) or 0)
				primer = round_price_list_rate(primer_sqft)
				screed = round_price_list_rate(sc_sqft)
				top_coat = round_price_list_rate(top_sqft)
				application = round_price_list_rate(app_rate)
				total = primer + screed + top_coat + application
				matrix.append(
					{
						"label": f"{system} TC {_thickness_label(top)} Screed {_thickness_label(sc)}",
						"system": system,
						"top_option": top,
						"screed_option": sc,
						"primer": primer,
						"screed": screed,
						"top_coat": top_coat,
						"application": application,
						"total": total,
						"primer_display": format_price_list_rate(primer_sqft),
						"screed_display": format_price_list_rate(sc_sqft),
						"top_coat_display": format_price_list_rate(top_sqft, blank_zero=True),
						"application_display": format_price_list_rate(app_rate),
						"total_display": format_price_list_rate(total),
					}
				)

	_append_block("Epoxy", PRICE_LIST_EPOXY_TOP, "top_coat_rate", epoxy_map)
	_append_block("PU", PRICE_LIST_PU_TOP, "pu_top_coat_rate", pu_map)

	return {
		"applicator_rate": round_price_list_rate(app_rate),
		"primer_per_sqft": round_price_list_rate(primer_sqft),
		"matrix": matrix,
		"unit_rates": {
			"epoxy": epoxy_units,
			"pu": pu_units,
			"screed": screed_units,
			"primer": [
				{
					"component": "Primer",
					"option": "-",
					"coverage": primer_cov,
					"rate_per_kit": _f(cfg.get("primer_rate")),
					"per_sqft": primer_sqft,
					"per_sqm": primer_sqm,
				}
			],
		},
		"kit_only": [
			{
				"component": "Coving",
				"rate_per_kit": _f(cfg.get("coving_rate")),
				"note": f"{_f(cfg.get('coving_coverage')) or 150:g} ft/kit · from project running feet",
			},
			{
				"component": "Hi-build",
				"rate_per_kit": _f(cfg.get("hibuild_rate")),
				"note": "Entered as kits per project (not from area)",
			},
		],
	}


def strip_gm_from_result(result):
	"""Remove GM fields from a calc_project result (for non–System Manager)."""
	if not result:
		return result

	def _strip_rows(rows):
		cleaned = []
		for row in rows or []:
			item = dict(row)
			item.pop("gm_per_kit", None)
			item.pop("gm_amount", None)
			cleaned.append(item)
		return cleaned

	out = dict(result)
	out.pop("margin_summary", None)
	# cost_profile is intentionally kept — no GM fields
	out["budget_rows"] = _strip_rows(out.get("budget_rows"))
	parts = []
	for part in out.get("part_budgets") or []:
		p = dict(part)
		p["budget_rows"] = _strip_rows(p.get("budget_rows"))
		parts.append(p)
	out["part_budgets"] = parts
	return out

def strip_gm_from_kit_rates(data):
	if not data:
		return data
	out = dict(data)
	for fieldname in GM_FIELDNAMES:
		out.pop(fieldname, None)
	revisions = []
	for row in out.get("rate_revisions") or []:
		rev = dict(row)
		for fieldname in GM_FIELDNAMES:
			rev.pop(fieldname, None)
		revisions.append(rev)
	if "rate_revisions" in out:
		out["rate_revisions"] = revisions
	return out

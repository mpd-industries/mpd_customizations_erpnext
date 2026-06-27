import math

import frappe
from frappe.model.document import Document

COMPONENTS = ("Top coat", "Screed", "Primer", "Coving", "Hi-build")

DEFAULT_RATES = {
	"top_coat_rate": 4230,
	"screed_rate": 3580,
	"primer_rate": 2012,
	"hibuild_rate": 1650,
	"coving_rate": 2800,
}

DEFAULT_COVERAGE = {
	"top_coat_500_coverage": 193,
	"top_coat_1mm_coverage": 139,
	"top_coat_2mm_coverage": 107,
	"screed_500_coverage": 150,
	"screed_1mm_coverage": 129,
	"screed_2mm_coverage": 96,
	"primer_coverage": 750,
}


def _f(value):
	try:
		return float(value or 0)
	except (TypeError, ValueError):
		return 0.0


def _ceil_div(numerator, denominator):
	if denominator <= 0:
		return 0
	return int(math.ceil(numerator / denominator))


def _coverage_for(settings, top_coat_option, screed_option):
	tc_map = {
		"500 micron": _f(settings.get("top_coat_500_coverage")),
		"1mm": _f(settings.get("top_coat_1mm_coverage")),
		"2mm": _f(settings.get("top_coat_2mm_coverage")),
	}
	sc_map = {
		"500 micron": _f(settings.get("screed_500_coverage")),
		"1mm": _f(settings.get("screed_1mm_coverage")),
		"2mm": _f(settings.get("screed_2mm_coverage")),
	}
	return tc_map.get(top_coat_option, tc_map["1mm"]), sc_map.get(screed_option, sc_map["1mm"])


def get_kit_rates_doc():
	try:
		rates = frappe.get_single("Kit rates")
	except Exception:
		rates = {}

	try:
		coverage = frappe.get_single("Kit Coverage")
	except Exception:
		coverage = {}

	values = {}
	for fieldname, fallback in DEFAULT_RATES.items():
		values[fieldname] = _f(_get_setting_value(rates, fieldname)) or float(fallback)
	for fieldname, fallback in DEFAULT_COVERAGE.items():
		values[fieldname] = _f(_get_setting_value(coverage, fieldname)) or float(fallback)
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


def calc_project(doc_or_dict, settings=None):
	data = _normalize_project_data(doc_or_dict)
	cfg = settings or get_kit_rates_doc()

	sqft = _f(data.get("sqft"))
	rate_per_sqft = _f(data.get("rate_per_sqft"))
	top_coat_option = data.get("top_coat_option") or "1mm"
	screed_option = data.get("screed_option") or "1mm"
	coving_kits = _f(data.get("coving_kits"))
	hibuild_kits = _f(data.get("hibuild_kits"))
	applicator_rate = _f(data.get("applicator_rate"))

	tc_cov, sc_cov = _coverage_for(cfg, top_coat_option, screed_option)
	pr_cov = _f(cfg.get("primer_coverage"))

	tc_kits = _ceil_div(sqft, tc_cov)
	sc_kits = _ceil_div(sqft, sc_cov)
	pr_kits = _ceil_div(sqft, pr_cov)

	tc_cost = tc_kits * _f(cfg.get("top_coat_rate"))
	sc_cost = sc_kits * _f(cfg.get("screed_rate"))
	pr_cost = pr_kits * _f(cfg.get("primer_rate"))
	co_cost = coving_kits * _f(cfg.get("coving_rate"))
	hi_cost = hibuild_kits * _f(cfg.get("hibuild_rate"))
	app_cost = applicator_rate * sqft

	contract = sqft * rate_per_sqft
	total = tc_cost + sc_cost + pr_cost + co_cost + hi_cost + app_cost
	profit_loss = contract - total
	margin_pct = (profit_loss / contract * 100) if contract else 0
	cost_per_sqft = (total / sqft) if sqft else 0

	budget_rows = [
		{
			"component": "Top coat",
			"option": top_coat_option,
			"coverage": tc_cov,
			"kits": tc_kits,
			"rate": _f(cfg.get("top_coat_rate")),
			"cost": tc_cost,
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
		row["cost_per_sqft"] = (row["cost"] / sqft) if sqft else 0

	return {
		"summary": {
			"contract_value": contract,
			"total_cost": total,
			"profit_loss": profit_loss,
			"margin_pct": margin_pct,
			"cost_per_sqft": cost_per_sqft,
		},
		"budget_rows": budget_rows,
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
		component = row.get("component") if isinstance(row, dict) else row.component
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

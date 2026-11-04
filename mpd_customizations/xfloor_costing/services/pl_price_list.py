import math

import frappe
from frappe.model.document import Document

from mpd_customizations.xfloor_costing.services.pl_constants import (
	EPOXY_TOP_COAT_OPTS,
	GM_FIELDNAMES,
	PU_TOP_COAT_OPTS,
	SCREED_OPTS,
	SQFT_PER_SQM,
)
from mpd_customizations.xfloor_costing.services.pl_helpers import (
	_epoxy_coverage_map,
	_f,
	_pu_coverage_map,
	_screed_coverage_map,
	get_kit_rates_doc,
)


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

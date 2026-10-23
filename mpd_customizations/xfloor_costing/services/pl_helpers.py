import math

import frappe
from frappe.model.document import Document

from mpd_customizations.xfloor_costing.services.pl_constants import (
	COMPONENT_ALIASES,
	DEFAULT_COVERAGE,
	DEFAULT_RATES,
	GM_FIELDNAMES,
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


def coving_kits_from_feet(feet, coverage):
	"""Kits of coving needed to cover ``feet`` of perimeter."""
	return _coving_kits_from_feet(feet, coverage)


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

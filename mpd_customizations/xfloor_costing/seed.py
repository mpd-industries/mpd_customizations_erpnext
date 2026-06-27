import frappe
from frappe.utils import today

from mpd_customizations.xfloor_costing.doctype.kit_coverage.kit_coverage import COVERAGE_FIELDS

DEFAULT_RATES = {
	"rates_effective_date": today(),
	"top_coat_rate": 4230,
	"screed_rate": 3580,
	"primer_rate": 2012,
	"hibuild_rate": 1650,
	"coving_rate": 2800,
}

DEFAULT_COVERAGE = {
	"coverage_effective_date": today(),
	"top_coat_500_coverage": 193,
	"top_coat_1mm_coverage": 139,
	"top_coat_2mm_coverage": 107,
	"screed_500_coverage": 150,
	"screed_1mm_coverage": 129,
	"screed_2mm_coverage": 96,
	"primer_coverage": 750,
}


def run():
	_migrate_coverage_from_kit_rates()
	_seed_doc("Kit rates", DEFAULT_RATES)
	_seed_doc("Kit Coverage", DEFAULT_COVERAGE)


def _seed_doc(doctype, defaults):
	doc = frappe.get_single(doctype)
	changed = False
	for key, value in defaults.items():
		if doc.get(key) in (None, "", 0):
			doc.set(key, value)
			changed = True

	if changed:
		doc.save(ignore_permissions=True)
		frappe.db.commit()


def _migrate_coverage_from_kit_rates():
	if not frappe.db.table_exists("tabKit rates"):
		return

	rates = frappe.get_single("Kit rates")
	coverage = frappe.get_single("Kit Coverage")
	changed = False

	for fieldname in COVERAGE_FIELDS:
		if rates.get(fieldname) and not coverage.get(fieldname):
			coverage.set(fieldname, rates.get(fieldname))
			changed = True

	if rates.get("coverage_effective_date") and not coverage.get("coverage_effective_date"):
		coverage.coverage_effective_date = rates.coverage_effective_date
		changed = True

	if changed:
		coverage.save(ignore_permissions=True)

	if frappe.db.table_exists("tabKit Coverage Revision"):
		frappe.db.sql(
			"""
			UPDATE `tabKit Coverage Revision`
			SET parent = %s, parenttype = %s
			WHERE parent = %s AND parenttype = %s
			""",
			("Kit Coverage", "Kit Coverage", "Kit rates", "Kit rates"),
		)
		frappe.db.commit()

import frappe
from frappe.utils import today

from mpd_customizations.xfloor_costing.doctype.kit_coverage.kit_coverage import COVERAGE_FIELDS

DEFAULT_RATES = {
	"rates_effective_date": today(),
	"top_coat_rate": 4230,
	"pu_top_coat_rate": 4230,
	"screed_rate": 3580,
	"primer_rate": 2012,
	"hibuild_rate": 1650,
	"coving_rate": 2800,
	"default_applicator_rate": 10,
	"top_coat_gm": 0,
	"pu_top_coat_gm": 0,
}

DEFAULT_COVERAGE = {
	"coverage_effective_date": today(),
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


def run():
	_migrate_coverage_from_kit_rates()
	_seed_doc("Kit rates", DEFAULT_RATES)
	_seed_doc("Kit Coverage", DEFAULT_COVERAGE)
	_backfill_dummy_from_thickest()
	_ensure_default_applicator_rate()


def _ensure_default_applicator_rate():
	"""Force commercial default applicator (₹10/sqft) when unset or still on old ₹7."""
	doc = frappe.get_single("Kit rates")
	current = doc.get("default_applicator_rate")
	if current in (None, "", 0, 7):
		doc.default_applicator_rate = 10
		doc.save(ignore_permissions=True)
		frappe.db.commit()


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


def _backfill_dummy_from_thickest():
	"""Fill missing PU / screed 3–7mm from thickest epoxy/screed without overwriting set values."""
	rates = frappe.get_single("Kit rates")
	coverage = frappe.get_single("Kit Coverage")
	changed_r = False
	changed_c = False

	if rates.get("pu_top_coat_rate") in (None, "", 0) and rates.get("top_coat_rate"):
		rates.pu_top_coat_rate = rates.top_coat_rate
		changed_r = True
	if rates.get("pu_top_coat_gm") in (None, "") and rates.get("top_coat_gm") is not None:
		rates.pu_top_coat_gm = rates.top_coat_gm or 0
		changed_r = True

	epoxy_2 = coverage.get("top_coat_2mm_coverage") or 107
	for mm in (3, 4):
		field = f"top_coat_{mm}mm_coverage"
		if coverage.get(field) in (None, "", 0):
			coverage.set(field, epoxy_2)
			changed_c = True

	pu_map = {
		"pu_top_coat_1mm_coverage": "top_coat_1mm_coverage",
		"pu_top_coat_2mm_coverage": "top_coat_2mm_coverage",
	}
	for dest, src in pu_map.items():
		if coverage.get(dest) in (None, "", 0) and coverage.get(src):
			coverage.set(dest, coverage.get(src))
			changed_c = True

	pu_2 = coverage.get("pu_top_coat_2mm_coverage") or coverage.get("top_coat_2mm_coverage") or 107
	for mm in (3, 4):
		field = f"pu_top_coat_{mm}mm_coverage"
		if coverage.get(field) in (None, "", 0):
			coverage.set(field, pu_2)
			changed_c = True

	screed_2 = coverage.get("screed_2mm_coverage") or 96
	for mm in range(3, 8):
		field = f"screed_{mm}mm_coverage"
		if coverage.get(field) in (None, "", 0):
			coverage.set(field, screed_2)
			changed_c = True

	if changed_r:
		rates.save(ignore_permissions=True)
	if changed_c:
		coverage.save(ignore_permissions=True)
	if changed_r or changed_c:
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

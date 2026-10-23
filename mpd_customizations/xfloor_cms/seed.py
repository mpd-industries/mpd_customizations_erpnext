"""
Xfloor CMS — idempotent bench seed script.

Run via bench execute:
    bench --site <site> execute mpd_customizations.xfloor_cms.seed.run

Run from bench console:
    from mpd_customizations.xfloor_cms.seed import run; run()
"""

import frappe

from mpd_customizations.xfloor_cms.seed_data import (
	SITE_SETTINGS,
	HOME_PAGE,
	ABOUT_PAGE,
	APPLICATOR_PAGE,
	CONTACT_PAGE,
	FAQ_PAGE,
	PRODUCTS,
	INDUSTRIES,
	TESTIMONIALS,
	GALLERY_ITEMS,
)



# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------












# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _upsert_singleton(doctype: str, data: dict) -> None:
	doc = frappe.get_single(doctype)
	doc.update(data)
	doc.save(ignore_permissions=True)
	print(f"  saved singleton  {doctype}")


def _upsert_by_name(doctype: str, name: str, data: dict) -> None:
	if frappe.db.exists(doctype, name):
		doc = frappe.get_doc(doctype, name)
		doc.update(data)
	else:
		doc = frappe.new_doc(doctype)
		doc.update(data)
	doc.save(ignore_permissions=True)
	print(f"  upserted  {doctype}/{name}")


def _upsert_by_field(doctype: str, unique_field: str, data: dict) -> None:
	existing = frappe.db.get_value(doctype, {unique_field: data[unique_field]}, "name")
	if existing:
		doc = frappe.get_doc(doctype, existing)
		doc.update(data)
	else:
		doc = frappe.new_doc(doctype)
		doc.update(data)
	doc.save(ignore_permissions=True)
	label = str(data[unique_field])[:60]
	print(f"  upserted  {doctype} [{unique_field}={label!r}]")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run() -> None:
	print("\n=== Xfloor CMS Seed ===")

	print("\n--- Singleton Pages ---")
	_upsert_singleton("XF Site Settings", SITE_SETTINGS)
	_upsert_singleton("XF Home Page", HOME_PAGE)
	_upsert_singleton("XF About Page", ABOUT_PAGE)
	_upsert_singleton("XF Applicator Page", APPLICATOR_PAGE)
	_upsert_singleton("XF Contact Page", CONTACT_PAGE)
	_upsert_singleton("XF FAQ Page", FAQ_PAGE)

	print("\n--- Product Systems ---")
	for p in PRODUCTS:
		_upsert_by_name("XF Product System", p["system_code"], p)

	print("\n--- Industry Profiles ---")
	for ind in INDUSTRIES:
		_upsert_by_name("XF Industry Profile", ind["name"], ind)

	print("\n--- Testimonials ---")
	for t in TESTIMONIALS:
		_upsert_by_field("XF Testimonial", "author", t)

	print("\n--- Gallery Items ---")
	for g in GALLERY_ITEMS:
		_upsert_by_field("XF Gallery Item", "caption", g)

	frappe.db.commit()
	print("\nDone — all records committed.\n")

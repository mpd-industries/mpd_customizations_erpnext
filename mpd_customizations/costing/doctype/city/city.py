import frappe
from frappe.model.document import Document


class City(Document):
	pass


def sync_cities_from_addresses():
	"""
	Pull every distinct non-blank city value from tabAddress into the City
	master. Safe to run repeatedly — skips cities that already exist.
	"""
	cities = frappe.db.sql(
		"SELECT DISTINCT city FROM tabAddress WHERE city IS NOT NULL AND city != '' ORDER BY city",
		as_dict=True,
	)
	inserted = 0
	for row in cities:
		city_name = (row.city or "").strip()
		if not city_name:
			continue
		if not frappe.db.exists("City", city_name):
			frappe.get_doc({"doctype": "City", "city_name": city_name}).insert(ignore_permissions=True)
			inserted += 1

	if inserted:
		frappe.db.commit()
		print(f"City sync: inserted {inserted} new city record(s) from Address table.")


def on_address_update(doc, method=None):
	"""Keep the City master in sync whenever an Address is saved."""
	city_name = (doc.city or "").strip()
	if city_name and not frappe.db.exists("City", city_name):
		frappe.get_doc({"doctype": "City", "city_name": city_name}).insert(ignore_permissions=True)

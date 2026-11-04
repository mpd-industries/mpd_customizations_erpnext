import frappe
from frappe.model.document import Document

from mpd_customizations.costing.services.city_sync import on_address_update, sync_cities_from_addresses

__all__ = ["on_address_update", "sync_cities_from_addresses"]


class City(Document):
	pass

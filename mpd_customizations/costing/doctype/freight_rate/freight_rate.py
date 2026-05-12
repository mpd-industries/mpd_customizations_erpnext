import frappe
from frappe.model.document import Document


class FreightRate(Document):
	def validate(self):
		if self.valid_from and self.valid_to:
			if self.valid_to < self.valid_from:
				frappe.throw(frappe._("Valid To must be on or after Valid From."))

		# Auto-fill city and country from the linked addresses
		if self.source_address:
			self.source_city = frappe.db.get_value("Address", self.source_address, "city") or ""
		if self.destination_address:
			addr = frappe.db.get_value("Address", self.destination_address, ["city", "country"], as_dict=True) or {}
			self.destination_city = addr.get("city") or ""
			self.destination_country = addr.get("country") or ""

		# Auto-set is_export
		if self.destination_country:
			india_names = frappe.get_all("Country", filters={"country_name": "India"}, fields=["name"], limit=1)
			india_name = india_names[0].name if india_names else "India"
			self.is_export = 1 if self.destination_country != india_name else 0
		else:
			self.is_export = 0

		if self.is_export and not self.forex_rate:
			frappe.throw(frappe._("Forex Rate is required for export destinations."))

	def on_submit(self):
		on_freight_rate_submitted(self)


def on_freight_rate_submitted(doc, method=None):
	_re_evaluate_affected_calculations(doc.destination_address, doc.customer or "")


def _re_evaluate_affected_calculations(destination_address: str, customer: str):
	from mpd_customizations.costing.services.config import get_config
	from mpd_customizations.costing.services.rate_source_registry import get_default_registry
	from mpd_customizations.costing.services.costing_engine import CostingEngine

	filters = {
		"customer_product_ref": ["is", "set"],
		"mode": ["not in", ["Approved", "Rejected"]],
		"docstatus": 0,
	}
	if customer:
		filters["customer"] = customer

	open_pcs = frappe.get_all("Pricing Calculation", filters=filters, fields=["name"])

	engine = CostingEngine(get_default_registry(), get_config())
	for pc in open_pcs:
		delivery_lines = frappe.get_all(
			"Costing Delivery Line",
			filters={
				"parent": pc.name,
				"parenttype": "Pricing Calculation",
				"destination_address": destination_address,
			},
			fields=["name"],
		)
		if delivery_lines:
			try:
				engine.evaluate(pc.name, "auto")
			except Exception:
				frappe.log_error(frappe.get_traceback(), f"Re-evaluate failed for {pc.name} after Freight Rate submit")

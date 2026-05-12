import frappe
from datetime import date, timedelta
from frappe.model.document import Document
from frappe.utils import getdate


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

	def before_submit(self):
		if not self.freight_per_kg:
			frappe.throw(frappe._("Freight Rate per kg is required before submitting."))
		if self.is_export and not self.forex_rate:
			frappe.throw(frappe._("Forex Rate is required for export destinations."))
		if not self.valid_to:
			self.valid_to = _end_of_quarter(getdate(self.valid_from) if self.valid_from else date.today())

	def on_submit(self):
		self._expire_overlapping_rates()
		on_freight_rate_submitted(self)

	def _expire_overlapping_rates(self):
		filters = {
			"source_address": self.source_address,
			"destination_address": self.destination_address,
			"transport_mode": self.transport_mode,
			"docstatus": 1,
			"name": ["!=", self.name],
		}

		this_from = getdate(self.valid_from)
		existing = frappe.get_all("Freight Rate", filters=filters, fields=["name", "valid_from", "valid_to"])
		for row in existing:
			ex_to = getdate(row.valid_to) if row.valid_to else None
			# overlaps if not entirely before or entirely after
			if ex_to is None or ex_to >= this_from:
				frappe.db.set_value("Freight Rate", row.name, "valid_to", this_from - timedelta(days=1))


def _end_of_quarter(d: date) -> date:
	quarter_end_month = ((d.month - 1) // 3 + 1) * 3  # 3, 6, 9, or 12
	# last day of quarter_end_month
	next_month = date(d.year + (1 if quarter_end_month == 12 else 0), (quarter_end_month % 12) + 1, 1)
	return next_month - timedelta(days=1)


def on_freight_rate_submitted(doc, method=None):
	_re_evaluate_affected_calculations(doc.destination_address)


def _re_evaluate_affected_calculations(destination_address: str):
	from mpd_customizations.costing.services.config import get_config
	from mpd_customizations.costing.services.rate_source_registry import get_default_registry
	from mpd_customizations.costing.services.costing_engine import CostingEngine

	open_pcs = frappe.get_all(
		"Pricing Calculation",
		filters={
			"customer_product_ref": ["is", "set"],
			"mode": ["not in", ["Approved", "Rejected"]],
			"docstatus": 0,
		},
		fields=["name"],
	)

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

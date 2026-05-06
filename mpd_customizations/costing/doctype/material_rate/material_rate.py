import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime, add_to_date, get_last_day, getdate

from mpd_customizations.costing import RateConflictError


class MaterialRate(Document):
	def validate(self):
		if not self.delivered_rate or self.delivered_rate <= 0:
			if self.docstatus == 0:
				self.delivered_rate = 0  # allow draft with no rate
			else:
				frappe.throw(_("Delivered Rate must be greater than 0."))

		if self.credit_days is None or self.credit_days < 0:
			frappe.throw(_("Supplier Credit Days must be 0 or greater."))

	def before_submit(self):
		if not self.supplier:
			frappe.throw(_("Supplier is required before submitting."))
		if not self.delivered_rate or self.delivered_rate <= 0:
			frappe.throw(_("Delivered Rate must be greater than 0 before submitting."))

		if not self.valid_to:
			self._set_default_valid_to()

		if self.valid_to and self.valid_from and getdate(self.valid_to) <= getdate(self.valid_from):
			frappe.throw(_("Valid To must be after Valid From."))

		if self.rate_type == "Ex-Works + Freight":
			self.delivered_rate = (self.ex_works_rate or 0) + (self.freight_per_unit or 0)

	def before_save(self):
		if self.rate_type == "Ex-Works + Freight":
			self.delivered_rate = (self.ex_works_rate or 0) + (self.freight_per_unit or 0)

	def on_submit(self):
		self._check_overlap()
		_notify_open_costing_requests(self)

	def _set_default_valid_to(self):
		from_date = getdate(self.valid_from) if self.valid_from else getdate()
		self.valid_to = get_last_day(from_date)

	def _check_overlap(self):
		filters = {
			"item": self.item,
			"supplier": self.supplier,
			"city": self.city,
			"docstatus": 1,
			"name": ["!=", self.name or ""],
		}
		existing_rates = frappe.get_all(
			"Material Rate",
			filters=filters,
			fields=["name", "valid_from", "valid_to"],
		)

		for existing in existing_rates:
			ex_from = getdate(existing.valid_from)
			ex_to = getdate(existing.valid_to) if existing.valid_to else None
			this_from = getdate(self.valid_from)
			this_to = getdate(self.valid_to) if self.valid_to else None

			far_future = getdate(add_to_date(now_datetime(), years=100))
			ex_to_cmp = ex_to if ex_to else far_future
			this_to_cmp = this_to if this_to else far_future

			if ex_from < this_to_cmp and ex_to_cmp > this_from:
				if self.flags.get("auto_expire_confirmed"):
					from datetime import timedelta
					new_valid_to = getdate(self.valid_from) - timedelta(days=1)
					frappe.db.set_value("Material Rate", existing.name, "valid_to", new_valid_to)
				else:
					raise RateConflictError(existing.name, existing.valid_from, existing.valid_to)


def _notify_open_costing_requests(doc):
	open_requests = frappe.get_all(
		"Costing Request",
		filters={"mode": ["in", ["Exploring", "Awaiting Rates", "Partially Costed"]], "docstatus": 0},
		fields=["name", "owner"],
	)

	if not open_requests:
		return

	city = doc.city
	for cr in open_requests:
		has_missing = frappe.db.exists(
			"Costing Rate Line",
			{"parent": cr.name, "item": doc.item, "city": city, "rate_freshness": ["in", ["Missing", "Expired"]]},
		)
		if has_missing:
			frappe.publish_realtime(
				"eval_js",
				f"frappe.show_alert({{message: 'New rate available for {doc.item_name or doc.item} — re-evaluate costing {cr.name}', indicator: 'green'}})",
				user=cr.owner,
			)

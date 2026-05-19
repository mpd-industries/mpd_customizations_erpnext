import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class ProcessingCharge(Document):
	def validate(self):
		if not self.item and not self.item_group:
			frappe.throw(_("At least one of Item or Item Group must be set."))

		if not self.charge_per_kg or self.charge_per_kg <= 0:
			frappe.throw(_("Charge per kg must be greater than 0."))

		if self.valid_to and self.valid_from and self.valid_to <= self.valid_from:
			frappe.throw(_("Valid To must be after Valid From."))

		self._check_overlap()

	def _check_overlap(self):
		filters = {
			"parent": self.parent,
			"parenttype": "Processor",
			"is_active": 1,
			"name": ["!=", self.name or ""],
		}
		if self.item:
			filters["item"] = self.item
		elif self.item_group:
			filters["item_group"] = self.item_group

		existing_charges = frappe.get_all(
			"Processing Charge",
			filters=filters,
			fields=["name", "valid_from", "valid_to"],
		)

		far_future = frappe.utils.add_years(now_datetime(), 100)
		for existing in existing_charges:
			ex_to_cmp = existing.valid_to if existing.valid_to else far_future
			this_to_cmp = self.valid_to if self.valid_to else far_future
			if existing.valid_from < this_to_cmp and ex_to_cmp > self.valid_from:
				frappe.throw(
					_("Overlap with existing Processing Charge {0}.").format(existing.name)
				)

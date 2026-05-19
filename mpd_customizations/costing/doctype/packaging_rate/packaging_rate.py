import frappe
from frappe.model.document import Document


class PackagingRate(Document):
	def validate(self):
		if self.valid_from and self.valid_to:
			if self.valid_to < self.valid_from:
				frappe.throw(frappe._("Valid To must be on or after Valid From."))


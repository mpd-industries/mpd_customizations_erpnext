import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, today

from mpd_customizations.costing.services.cost_calculator import compute_additional_charge_amount


class PricingCalculation(Document):
	def before_insert(self):
		if not self.valid_until:
			self.valid_until = add_days(today(), 7)

	def validate(self):
		if self.solids_content_pct is not None:
			if not (0 < self.solids_content_pct < 100):
				frappe.throw(_("Solids Content % must be between 0 and 100 (exclusive)."))

		if self.production_days is not None and self.production_days <= 0:
			frappe.throw(_("Production Days must be positive."))

		if self.supplier_financing_rate_pct is not None and self.supplier_financing_rate_pct <= 0:
			frappe.throw(_("Supplier Financing Rate must be positive."))

		if self.item:
			bom_exists = frappe.db.exists("BOM", {"item": self.item})
			if not bom_exists:
				frappe.throw(
					_("Item {0} has no BOM. Only items with a BOM can be costed.").format(self.item)
				)

		solids = self.solids_content_pct or 0
		for charge in self.additional_charges or []:
			charge.amount_per_kg = compute_additional_charge_amount(
				charge.rate or 0, charge.basis, solids
			)

	def before_submit(self):
		if self.mode != "Approved":
			frappe.throw(_("Cannot submit — Pricing Calculation must be in Approved mode first."))

	def on_trash(self):
		frappe.db.delete("Costing Material Line", {"pricing_calculation": self.name})
		frappe.db.delete("Costing Combination", {"pricing_calculation": self.name})

	def sync_status_to_request(self):
		if not self.pricing_request:
			return
		update = {"status": self.mode}
		if self.confirmed_ex_factory_cost_per_kg:
			update["confirmed_price_per_kg"] = self.confirmed_ex_factory_cost_per_kg
			pr = frappe.get_doc("Pricing Request", self.pricing_request)
			qty = pr.quantity_kg or 0
			update["total_price"] = qty * self.confirmed_ex_factory_cost_per_kg
		frappe.db.set_value("Pricing Request", self.pricing_request, update)

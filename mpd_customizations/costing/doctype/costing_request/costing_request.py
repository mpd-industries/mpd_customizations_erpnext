import frappe
from frappe import _
from frappe.model.document import Document

from mpd_customizations.costing.services.cost_calculator import compute_additional_charge_amount


class CostingRequest(Document):
	def on_load(self):
		if self.is_new():
			config = frappe.get_single("Costing Configuration")
			self.production_days = config.production_days or 30
			self.fetched_production_days = self.production_days
			self.supplier_financing_rate_pct = config.supplier_financing_rate_pct or 12.0
			self.fetched_supplier_financing_rate_pct = self.supplier_financing_rate_pct
			self.mode = "Exploring"

	def validate(self):
		if self.solids_content_pct is not None:
			if not (0 < self.solids_content_pct < 100):
				frappe.throw(_("Solids Content % must be between 0 and 100 (exclusive)."))

		if self.production_days is not None and self.production_days <= 0:
			frappe.throw(_("Production Days must be positive."))

		if self.supplier_financing_rate_pct is not None and self.supplier_financing_rate_pct <= 0:
			frappe.throw(_("Supplier Financing Rate must be positive."))

		if self.item:
			bom_exists = frappe.db.exists(
				"BOM", {"item": self.item}
			)
			if not bom_exists:
				frappe.throw(
					_("Item {0} has no BOM. Only items with a BOM can be costed.").format(
						self.item
					)
				)

		solids = self.solids_content_pct or 0
		for charge in self.additional_charges or []:
			charge.amount_per_kg = compute_additional_charge_amount(
				charge.rate or 0, charge.basis, solids
			)

	def before_submit(self):
		from mpd_customizations.costing.services.rate_fetcher import RateFetcher

		fetch_result = RateFetcher.fetch(self, preserve_overrides=True)

		if self.selected_combination:
			missing_items = []
			material_lines = frappe.get_all(
				"Costing Material Line",
				filters={"combination": self.selected_combination},
				fields=["item", "item_name", "rate_freshness", "working_rate"],
			)
			for line in material_lines:
				if line.rate_freshness == "Missing":
					missing_items.append(line.item_name or line.item)

			if missing_items:
				frappe.throw(
					_("Cannot submit: missing rates for {0} in selected formulation.").format(
						", ".join(missing_items)
					)
				)

		frappe.db.set_value("Costing Request", self.name, "mode", "Pending Approval")

	def on_submit(self):
		frappe.db.set_value("Costing Request", self.name, "mode", "Approved")

	def on_cancel(self):
		frappe.db.set_value("Costing Request", self.name, "mode", "Exploring")

	def on_trash(self):
		frappe.db.delete("Costing Material Line", {"costing_request": self.name})
		frappe.db.delete("Costing Combination", {"costing_request": self.name})

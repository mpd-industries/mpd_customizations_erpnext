import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, today

from mpd_customizations.costing.services.cost_calculator import compute_additional_charge_amount
from mpd_customizations.costing.services.costing_engine import build_cost_summary, find_selected_combo


class PricingCalculation(Document):
	ignore_linked_doctypes = ["Pricing Request", "Material Rate", "Freight Rate"]

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

		if self.customer_product_ref:
			# Customer Quote mode — sync export flag from Customer Product
			cp_is_export = frappe.db.get_value("Customer Product", self.customer_product_ref, "is_export") or 0
			self.is_export = cp_is_export
		elif self.item:
			bom_exists = frappe.db.exists("BOM", {"item": self.item})
			if not bom_exists:
				frappe.throw(
					_("Item {0} has no BOM. Only items with a BOM can be costed.").format(self.item)
				)

		# Recompute packaging line derived fields
		for pl in self.packaging_lines or []:
			fill = pl.fill_quantity_kg or 0
			if fill:
				pl.packages_per_kg = 1.0 / fill
				if pl.working_rate_per_unit is not None:
					pl.working_rate_per_kg = (pl.working_rate_per_unit or 0) / fill
				pl.packaging_cost_per_kg = pl.working_rate_per_kg or 0
			else:
				pl.packages_per_kg = 0
				pl.packaging_cost_per_kg = 0

		# Recompute delivery line derived fields
		for dl in self.delivery_lines or []:
			dl.delivery_cost_per_kg_inr = dl.working_freight_per_kg or 0

		solids = self.solids_content_pct or 0
		for charge in self.additional_charges or []:
			charge.amount_per_kg = compute_additional_charge_amount(
				charge.rate or 0, charge.basis, solids
			)

	def before_submit(self):
		if self.mode != "Approved":
			frappe.throw(_("Cannot submit — Pricing Calculation must be in Approved mode first."))

	def on_submit(self):
		if not self.pricing_request:
			return
		raw = frappe.parse_json(self.costing_raw) if self.costing_raw else {}
		combinations = raw.get("combinations") or []
		combo = find_selected_combo(combinations, self.selected_combination)
		if not combo:
			return
		summary = build_cost_summary(combo, raw)
		# JSON must be serialized before set_value — labels contain "%" (e.g. credit rate)
		frappe.db.set_value(
			"Pricing Request",
			self.pricing_request,
			"cost_summary_json",
			frappe.as_json(summary),
			update_modified=False,
		)

	def on_trash(self):
		if self.pricing_request:
			frappe.db.set_value("Pricing Request", self.pricing_request, "pricing_calculation", "")
		frappe.db.delete("Material Rate", {"pricing_calculation": self.name, "docstatus": 0})
		if frappe.db.has_column("Freight Rate", "pricing_calculation"):
			frappe.db.delete("Freight Rate", {"pricing_calculation": self.name, "docstatus": 0})

	def sync_status_to_request(self):
		if not self.pricing_request:
			return
		frappe.db.set_value("Pricing Request", self.pricing_request, {"status": self.mode})

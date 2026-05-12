import frappe
from frappe.model.document import Document


class PackagingRate(Document):
	def validate(self):
		if self.valid_from and self.valid_to:
			if self.valid_to < self.valid_from:
				frappe.throw(frappe._("Valid To must be on or after Valid From."))

	def on_submit(self):
		on_packaging_rate_submitted(self)


def on_packaging_rate_submitted(doc, method=None):
	_re_evaluate_affected_calculations(doc.packaging_material)


def _re_evaluate_affected_calculations(packaging_material: str):
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
		pkg_lines = frappe.get_all(
			"Costing Packaging Line",
			filters={"parent": pc.name, "parenttype": "Pricing Calculation", "packaging_material": packaging_material},
			fields=["name"],
		)
		if pkg_lines:
			try:
				engine.evaluate(pc.name, "auto")
			except Exception:
				frappe.log_error(frappe.get_traceback(), f"Re-evaluate failed for {pc.name} after Packaging Rate submit")

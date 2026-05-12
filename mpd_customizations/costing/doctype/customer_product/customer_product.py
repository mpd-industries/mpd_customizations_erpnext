import frappe
from frappe import _
from frappe.model.document import Document

_SALES_FIELDS = frozenset([
	"customer", "customer_product_code", "product_description",
	"packaging_material", "fill_quantity_kg", "packaging_description",
	"delivery_address", "delivery_city", "delivery_country", "is_export", "is_active",
	"incoterms", "credit_days", "transport_mode", "margin_type", "margin_rate",
])


class CustomerProduct(Document):
	def validate(self):
		self._compute_is_export()
		self._enforce_field_ownership()
		self._validate_formulation_solids()

	def _compute_is_export(self):
		if self.delivery_country:
			india_names = frappe.get_all("Country", filters={"country_name": "India"}, fields=["name"], limit=1)
			india_name = india_names[0].name if india_names else "India"
			self.is_export = 1 if self.delivery_country != india_name else 0
		else:
			self.is_export = 0

	def _validate_formulation_solids(self):
		solids_values = {}
		for row in (self.formulations or []):
			if not row.bom:
				continue
			item = frappe.db.get_value("BOM", row.bom, "item")
			if not item:
				continue
			solids = frappe.db.get_value("Item", item, "custom_solids_content_pct") or 0
			solids_values[row.bom] = solids

		unique = set(solids_values.values())
		if len(unique) > 1:
			detail = ", ".join(f"{bom}={s}%" for bom, s in solids_values.items())
			frappe.throw(
				_("All formulations must have the same Solids Content %. Found: {0}").format(detail)
			)

	def _enforce_field_ownership(self):
		roles = set(frappe.get_roles())
		is_sys = "System Manager" in roles
		if is_sys:
			return

		is_rd = "R&D Manager" in roles
		is_sales = "Costing Sales" in roles

		if self.is_new():
			return

		old = self.get_doc_before_save()
		if not old:
			return

		if is_rd and not is_sales:
			# R&D may only change formulations — restore all Sales-owned fields
			for f in _SALES_FIELDS:
				setattr(self, f, getattr(old, f, None))
			self.commissions = old.commissions or []

		if is_sales and not is_rd:
			# Sales may only change non-formulation fields — restore formulations
			self.formulations = old.formulations or []

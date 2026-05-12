import frappe
from frappe import _
from frappe.model.document import Document


class PricingRequest(Document):
	def after_insert(self):
		_create_calculation(self)
		if self.pricing_calculation:
			_run_initial_evaluation(self.pricing_calculation)
		frappe.publish_realtime(
			"eval_js",
			f"if(cur_frm&&cur_frm.doctype==='Pricing Request'&&cur_frm.docname==='{self.name}'){{cur_frm.reload_doc();}}",
			user=frappe.session.user,
		)

	def validate(self):
		if not self.product and not self.customer_product:
			frappe.throw(_("Either Product or Customer Product is required."))

		if self.solids_content_pct is not None:
			if not (0 < self.solids_content_pct < 100):
				frappe.throw(_("Solids Content % must be between 0 and 100 (exclusive)."))

		# Auto-fill city from Customer Product delivery destination if not set
		if self.customer_product and not self.city:
			delivery_city = frappe.db.get_value("Customer Product", self.customer_product, "delivery_city")
			if delivery_city:
				self.city = delivery_city

		if self.quantity_kg and self.confirmed_price_per_kg:
			self.total_price = self.quantity_kg * self.confirmed_price_per_kg
		else:
			self.total_price = 0

	def before_submit(self):
		if self.status != "Ready to Quote":
			frappe.throw(
				_("Cannot submit — status must be 'Ready to Quote'. Current status: {0}").format(self.status)
			)
		self.status = "Pending Approval"

	def on_cancel(self):
		frappe.db.set_value("Pricing Request", self.name, "status", "Draft")


def _run_initial_evaluation(pc_name):
	from mpd_customizations.costing.services.config import get_config
	from mpd_customizations.costing.services.rate_source_registry import get_default_registry
	from mpd_customizations.costing.services.costing_engine import CostingEngine
	try:
		CostingEngine(get_default_registry(), get_config()).evaluate(pc_name, "auto")
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"Initial evaluation failed for {pc_name}")


def _create_calculation(pr):
	config = frappe.get_single("Costing Configuration")

	pc_data = {
		"doctype": "Pricing Calculation",
		"pricing_request": pr.name,
		"city": pr.city,
		"solids_content_pct": pr.solids_content_pct or 0,
		"mode": "Draft",
		"production_days": config.production_days or 30,
		"fetched_production_days": config.production_days or 30,
		"supplier_financing_rate_pct": config.supplier_financing_rate_pct or 12.0,
		"fetched_supplier_financing_rate_pct": config.supplier_financing_rate_pct or 12.0,
	}

	if pr.customer_product:
		# Customer Quote mode — populate from Customer Product
		cp = frappe.get_doc("Customer Product", pr.customer_product)
		pc_data["customer_product_ref"] = pr.customer_product
		pc_data["customer"] = cp.customer
		pc_data["customer_product_code"] = cp.customer_product_code
		pc_data["is_export"] = cp.is_export or 0
		if not pr.city and cp.delivery_city:
			pc_data["city"] = cp.delivery_city
	else:
		cp = None
		pc_data["item"] = pr.product

	pc = frappe.get_doc(pc_data)

	if cp:
		# Pre-populate packaging line from Customer Product default
		if cp.packaging_material:
			pc.append("packaging_lines", {
				"packaging_material": cp.packaging_material,
				"fill_quantity_kg": cp.fill_quantity_kg or 1.0,
			})
		# Pre-populate delivery line from Customer Product
		if cp.delivery_country:
			pc.append("delivery_lines", {
				"destination_city": cp.delivery_city or "",
				"destination_country": cp.delivery_country,
				"is_export": cp.is_export or 0,
			})

	# Pre-fill from last approved request
	prev = _get_previous_approved(pr.product or None, pr.customer_product or None, pr.city)
	if prev:
		pc.preferred_bom = prev.get("preferred_bom") or ""
		pc.production_days = prev.get("production_days") or pc.production_days
		pc.fetched_production_days = pc.production_days
		pc.supplier_financing_rate_pct = prev.get("supplier_financing_rate_pct") or pc.supplier_financing_rate_pct
		pc.fetched_supplier_financing_rate_pct = pc.supplier_financing_rate_pct

		additional_charges = frappe.get_all(
			"Costing Additional Charge",
			filters={"parent": prev["name"], "parenttype": "Pricing Calculation"},
			fields=["description", "basis", "rate"],
		)
		for c in additional_charges:
			pc.append("additional_charges", {
				"description": c.description,
				"basis": c.basis,
				"rate": c.rate,
			})

		frappe.db.set_value("Pricing Request", pr.name, "previous_pricing_ref", prev["name"])

		if prev.get("processor"):
			pc.processor = prev["processor"]

		prev_processing = frappe.get_all(
			"Costing Processing Line",
			filters={"parent": prev["name"], "parenttype": "Pricing Calculation"},
			fields=[
				"processor", "processing_charge_ref",
				"fetched_charge_per_kg", "fetched_freight_per_unit", "fetched_includes_outward_freight",
				"working_charge_per_kg", "working_freight_per_unit", "working_includes_outward_freight",
			],
		)
		for pl in prev_processing:
			pc.append("processing_lines", {
				"processor": pl.processor,
				"processing_charge_ref": pl.processing_charge_ref,
				"fetched_charge_per_kg": pl.fetched_charge_per_kg,
				"fetched_freight_per_unit": pl.fetched_freight_per_unit,
				"fetched_includes_outward_freight": pl.fetched_includes_outward_freight,
				"working_charge_per_kg": pl.working_charge_per_kg,
				"working_freight_per_unit": pl.working_freight_per_unit,
				"working_includes_outward_freight": pl.working_includes_outward_freight,
			})

	pc.insert(ignore_permissions=True)
	frappe.db.set_value("Pricing Request", pr.name, "pricing_calculation", pc.name)

	# Notify costing team
	_notify_costing_team(pr, pc.name)


def _get_previous_approved(product, customer_product, city):
	if customer_product:
		filters = {"customer_product_ref": customer_product, "mode": "Approved"}
	elif product:
		filters = {"item": product, "city": city, "mode": "Approved"}
	else:
		return None

	results = frappe.get_all(
		"Pricing Calculation",
		filters=filters,
		fields=["name", "preferred_bom", "production_days", "supplier_financing_rate_pct",
		        "confirmed_ex_factory_cost_per_kg", "processor"],
		order_by="modified desc",
		limit=1,
	)
	return results[0] if results else None


def _notify_costing_team(pr, calc_name):
	costing_users = frappe.get_all(
		"Has Role",
		filters={"role": "Costing User", "parenttype": "User"},
		fields=["parent"],
	)
	for u in costing_users:
		frappe.publish_realtime(
			"eval_js",
			f"frappe.show_alert({{message: 'New Pricing Request {pr.name} — {pr.product_name or pr.product} ({pr.city}) [Priority: {pr.priority}]', indicator: 'blue'}})",
			user=u.parent,
		)

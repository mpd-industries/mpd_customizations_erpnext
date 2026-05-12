import frappe
from frappe import _
from frappe.utils import now_datetime

from mpd_customizations.costing.services.config import get_config
from mpd_customizations.costing.services.cost_calculator import compute_internal_earnings
from mpd_customizations.costing.services.rate_source_registry import get_default_registry

STANDARD_COSTED_PRICE_LIST = "Standard Costed"
QUOTE_VALIDITY_DAYS = 14


@frappe.whitelist()
def evaluate(pricing_calculation_name: str, trigger: str = "manual"):
	frappe.has_permission("Pricing Calculation", "write", throw=True)
	return _run_evaluate(pricing_calculation_name, trigger)


def _run_evaluate(pricing_calculation_name: str, trigger: str = "override"):
	from mpd_customizations.costing.services.costing_engine import CostingEngine
	return CostingEngine(get_default_registry(), get_config()).evaluate(pricing_calculation_name, trigger)


@frappe.whitelist()
def get_combinations(pricing_calculation_name: str):
	frappe.has_permission("Pricing Calculation", "read", throw=True)

	combos = frappe.get_all(
		"Costing Combination",
		filters={"pricing_calculation": pricing_calculation_name},
		fields=[
			"name", "bom", "formulation_id", "formulation_description", "prev_rm_cost_per_kg",
			"rank", "delta_pct", "status",
			"is_preferred", "is_selected", "rm_cost_per_kg", "financing_cost_per_kg",
			"processing_cost_per_kg", "additional_charges_per_kg", "outward_freight_per_kg",
			"total_cost_per_kg", "missing_items", "expired_items",
		],
	)

	combo_names = [c.name for c in combos]
	if combo_names:
		material_lines = frappe.get_all(
			"Costing Material Line",
			filters={"combination": ["in", combo_names]},
			fields=[
				"combination", "item", "item_name", "uom", "qty_per_kg_output",
				"supplier", "city", "rate_freshness", "working_rate",
				"working_supplier_credit_days", "net_financed_days",
				"amount_per_kg", "financing_cost_per_kg", "equalized_amount_per_kg",
				"is_scrap", "confidence_score",
			],
		)
		ml_map = {}
		for ml in material_lines:
			ml_map.setdefault(ml.combination, []).append(ml)

		for combo in combos:
			combo["material_lines"] = ml_map.get(combo.name, [])

	return combos


@frappe.whitelist()
def select_combination(pricing_calculation_name: str, combination_name: str):
	frappe.has_permission("Pricing Calculation", "write", throw=True)

	frappe.db.set_value("Costing Combination", {"pricing_calculation": pricing_calculation_name}, "is_selected", 0)
	combo = frappe.get_doc("Costing Combination", combination_name)
	frappe.db.set_value("Costing Combination", combination_name, "is_selected", 1)

	doc = frappe.get_doc("Pricing Calculation", pricing_calculation_name)
	new_mode = "Ready to Quote" if combo.status in ("Ready to Quote", "Indicative — Rates Expired") else doc.mode
	frappe.db.set_value(
		"Pricing Calculation",
		pricing_calculation_name,
		{
			"selected_combination": combination_name,
			"confirmed_ex_factory_cost_per_kg": combo.total_cost_per_kg,
			"mode": new_mode,
		},
	)

	# Sync to Pricing Request
	if doc.pricing_request:
		qty = frappe.db.get_value("Pricing Request", doc.pricing_request, "quantity_kg") or 0
		frappe.db.set_value("Pricing Request", doc.pricing_request, {
			"status": new_mode,
			"confirmed_price_per_kg": combo.total_cost_per_kg,
			"total_price": qty * combo.total_cost_per_kg,
		})

	return {"confirmed_ex_factory_cost_per_kg": combo.total_cost_per_kg, "mode": new_mode}


@frappe.whitelist()
def apply_rate_override(
	pricing_calculation_name: str,
	item: str,
	working_rate: float,
	working_supplier_credit_days: int,
	reason: str = "",
):
	frappe.has_permission("Pricing Calculation", "write", throw=True)

	doc = frappe.get_doc("Pricing Calculation", pricing_calculation_name)
	for rl in doc.rate_lines:
		if rl.item == item:
			rl.working_rate = float(working_rate)
			rl.working_supplier_credit_days = int(working_supplier_credit_days)
			rl.override_reason = reason
			break

	doc.save(ignore_permissions=True)
	return _run_evaluate(pricing_calculation_name)


@frappe.whitelist()
def apply_processing_override(
	pricing_calculation_name: str,
	working_charge_per_kg: float,
	working_freight_per_unit: float,
	working_includes_outward_freight: int,
	reason: str = "",
):
	frappe.has_permission("Pricing Calculation", "write", throw=True)

	doc = frappe.get_doc("Pricing Calculation", pricing_calculation_name)
	if doc.processing_lines:
		pl = doc.processing_lines[0]
		pl.working_charge_per_kg = float(working_charge_per_kg)
		pl.working_freight_per_unit = float(working_freight_per_unit)
		pl.working_includes_outward_freight = int(working_includes_outward_freight)
		pl.override_reason = reason

	doc.save(ignore_permissions=True)
	return _run_evaluate(pricing_calculation_name)


@frappe.whitelist()
def revert_rate_override(pricing_calculation_name: str, item: str):
	frappe.has_permission("Pricing Calculation", "write", throw=True)

	doc = frappe.get_doc("Pricing Calculation", pricing_calculation_name)
	for rl in doc.rate_lines:
		if rl.item == item:
			rl.working_rate = rl.fetched_rate
			rl.working_supplier_credit_days = rl.fetched_supplier_credit_days
			rl.override_reason = ""
			break

	doc.save(ignore_permissions=True)
	return _run_evaluate(pricing_calculation_name)


@frappe.whitelist()
def recompute_combinations(pricing_calculation_name: str):
	frappe.has_permission("Pricing Calculation", "write", throw=True)
	return _run_evaluate(pricing_calculation_name)


@frappe.whitelist()
def promote_freight_overrides_to_master(pricing_calculation_name: str):
	frappe.has_permission("Pricing Calculation", "write", throw=True)

	doc = frappe.get_doc("Pricing Calculation", pricing_calculation_name)

	source_address = ""
	if doc.processor:
		source_address = frappe.db.get_value("Processor", doc.processor, "address") or ""

	created = []
	skipped = []

	for dl in doc.delivery_lines or []:
		working_rate = dl.working_freight_per_kg or 0
		if not working_rate:
			continue

		is_missing = dl.rate_freshness == "Missing"
		is_overridden = round(working_rate, 4) != round(dl.fetched_freight_per_kg or 0, 4)
		if not (is_missing or is_overridden):
			continue

		dest_address = dl.destination_address
		if not dest_address or not source_address:
			skipped.append(dest_address or "Unknown")
			continue

		transport_mode = dl.transport_mode or "Barrels"
		customer = doc.customer or ""
		customer_product = doc.customer_product_ref or ""

		existing_filters = {
			"source_address": source_address,
			"destination_address": dest_address,
			"transport_mode": transport_mode,
			"docstatus": 0,
		}
		if customer:
			existing_filters["customer"] = customer
		if customer_product:
			existing_filters["customer_product"] = customer_product

		existing = frappe.db.exists("Freight Rate", existing_filters)
		if existing:
			skipped.append(existing)
			continue

		new_doc = frappe.get_doc({
			"doctype": "Freight Rate",
			"source_address": source_address,
			"destination_address": dest_address,
			"transport_mode": transport_mode,
			"customer": customer,
			"customer_product": customer_product,
			"freight_per_kg": working_rate,
			"currency": dl.working_currency or "",
			"forex_rate": dl.working_forex_rate or 0,
			"valid_from": frappe.utils.today(),
		})
		new_doc.insert(ignore_permissions=True)
		created.append({"name": new_doc.name, "destination": dest_address, "transport_mode": transport_mode})

	return {"created": created, "skipped": skipped}


@frappe.whitelist()
def revert_all_overrides(pricing_calculation_name: str):
	frappe.has_permission("Pricing Calculation", "write", throw=True)

	doc = frappe.get_doc("Pricing Calculation", pricing_calculation_name)
	for rl in doc.rate_lines:
		rl.working_rate = rl.fetched_rate
		rl.working_supplier_credit_days = rl.fetched_supplier_credit_days
		rl.override_reason = ""

	if doc.processing_lines:
		pl = doc.processing_lines[0]
		pl.working_charge_per_kg = pl.fetched_charge_per_kg
		pl.working_freight_per_unit = pl.fetched_freight_per_unit
		pl.working_includes_outward_freight = pl.fetched_includes_outward_freight
		pl.override_reason = ""

	doc.save(ignore_permissions=True)
	return _run_evaluate(pricing_calculation_name)


@frappe.whitelist()
def create_pending_rates(pricing_calculation_name: str):
	frappe.has_permission("Pricing Calculation", "write", throw=True)

	doc = frappe.get_doc("Pricing Calculation", pricing_calculation_name)
	priority = "Normal"
	product = ""
	if doc.pricing_request:
		pr_values = frappe.db.get_value(
			"Pricing Request", doc.pricing_request, ["priority", "product"], as_dict=True
		) or {}
		priority = pr_values.get("priority") or "Normal"
		product = pr_values.get("product") or ""

	if doc.rate_lines:
		items_needing_rates = [
			rl.item for rl in doc.rate_lines
			if rl.rate_freshness in ("Missing", "Expired")
		]
	else:
		items_needing_rates = _get_bom_items_without_current_rate(doc.item, doc.city)

	if not frappe.db.has_column("Material Rate", "pricing_calculation"):
		return {"created_count": 0, "error": "Run bench migrate first to add new fields to Material Rate"}

	created = 0
	for item in items_needing_rates:
		existing = frappe.db.exists(
			"Material Rate",
			{"item": item, "city": doc.city, "docstatus": 0},
		)
		if not existing:
			frappe.get_doc({
				"doctype": "Material Rate",
				"item": item,
				"city": doc.city,
				"pricing_calculation": pricing_calculation_name,
				"pricing_request": doc.pricing_request or "",
				"product": product,
				"priority": priority,
				"requested_on": now_datetime(),
				"uom": frappe.db.get_value("Item", item, "stock_uom") or "Kg",
				"rate_type": "All-In Delivered",
				"valid_from": frappe.utils.today(),
			}).insert(ignore_permissions=True)
			created += 1

	freight_created = _create_missing_freight_rates(doc)

	return {"created_count": created, "freight_created_count": freight_created}


def _create_missing_freight_rates(doc) -> int:
	source_address = ""
	if doc.processor:
		source_address = frappe.db.get_value("Processor", doc.processor, "address") or ""
	if not source_address:
		return 0

	customer = doc.customer or ""
	customer_product = doc.customer_product_ref or ""
	created = 0

	for dl in doc.delivery_lines or []:
		if dl.rate_freshness != "Missing":
			continue
		if not dl.destination_address:
			continue

		transport_mode = dl.transport_mode or "Barrels"
		existing_filters = {
			"source_address": source_address,
			"destination_address": dl.destination_address,
			"transport_mode": transport_mode,
			"docstatus": ["in", [0, 1]],
		}
		if customer:
			existing_filters["customer"] = customer
		if customer_product:
			existing_filters["customer_product"] = customer_product

		if frappe.db.exists("Freight Rate", existing_filters):
			continue

		frappe.get_doc({
			"doctype": "Freight Rate",
			"source_address": source_address,
			"destination_address": dl.destination_address,
			"transport_mode": transport_mode,
			"customer": customer,
			"customer_product": customer_product,
			"freight_per_kg": 0,
			"valid_from": frappe.utils.today(),
		}).insert(ignore_permissions=True)
		created += 1

	return created


def _get_bom_items_without_current_rate(product_item: str, city: str) -> list:
	today = frappe.utils.today()
	boms = frappe.get_all(
		"BOM",
		filters={"item": product_item},
		fields=["name"],
	)
	if not boms:
		return []

	seen = set()
	result = []
	for bom in boms:
		bom_items = frappe.get_all(
			"BOM Item",
			filters={"parent": bom.name},
			fields=["item_code"],
		)
		for bi in bom_items:
			item_code = bi.item_code
			if item_code in seen:
				continue
			seen.add(item_code)
			has_rate = frappe.db.exists(
				"Material Rate",
				{
					"item": item_code,
					"city": city,
					"docstatus": 1,
					"valid_from": ["<=", today],
					"valid_to": [">=", today],
				},
			)
			if not has_rate:
				result.append(item_code)

	return result


@frappe.whitelist()
def get_cost_breakdown(pricing_calculation_name: str):
	frappe.has_permission("Pricing Calculation", "read", throw=True)

	doc = frappe.get_doc("Pricing Calculation", pricing_calculation_name)
	if not doc.selected_combination:
		return {}

	combo = frappe.get_doc("Costing Combination", doc.selected_combination)
	material_lines = frappe.get_all(
		"Costing Material Line",
		filters={"combination": doc.selected_combination},
		fields=[
			"item", "item_name", "uom", "qty_per_kg_output", "supplier", "city",
			"rate_freshness", "working_rate", "working_supplier_credit_days",
			"net_financed_days", "amount_per_kg", "financing_cost_per_kg",
			"equalized_amount_per_kg", "is_scrap",
		],
	)

	rate_lines_map = {rl.item: rl for rl in (doc.rate_lines or [])}
	for ml in material_lines:
		rl = rate_lines_map.get(ml.item)
		ml["fetched_rate"] = rl.fetched_rate if rl else None
		ml["rate_source_ref"] = rl.rate_source_ref if rl else None
		ml["is_overridden"] = bool(
			rl and rl.fetched_rate and
			round(rl.working_rate or 0, 2) != round(rl.fetched_rate, 2)
		)

	layer1 = {
		"formulation_id": combo.formulation_id,
		"bom": combo.bom,
		"material_lines": [dict(ml) for ml in material_lines],
		"rm_cost_per_kg": combo.rm_cost_per_kg,
		"financing_cost_per_kg": combo.financing_cost_per_kg,
		"processing_cost_per_kg": combo.processing_cost_per_kg,
		"additional_charges_per_kg": combo.additional_charges_per_kg,
		"additional_charges": [
			{"description": c.description, "basis": c.basis, "rate": c.rate, "amount_per_kg": c.amount_per_kg}
			for c in (doc.additional_charges or [])
		],
		"outward_freight_per_kg": combo.outward_freight_per_kg,
		"total_cost_per_kg": combo.total_cost_per_kg,
		"production_days": doc.production_days,
		"supplier_financing_rate_pct": doc.supplier_financing_rate_pct,
		"processing_charge_ref": combo.processing_charge_ref,
		"solids_content_pct": doc.solids_content_pct,
	}

	result = {"layer1": layer1}

	if set(frappe.get_roles(frappe.session.user)) & {"Costing Approver", "System Manager"}:
		config = get_config()
		ml_dicts = [
			{
				"item": ml["item"],
				"item_name": ml["item_name"],
				"amount_per_kg": ml["amount_per_kg"],
				"net_financed_days": ml["net_financed_days"],
			}
			for ml in material_lines
		]
		layer3 = compute_internal_earnings(
			ml_dicts,
			config.actual_cost_of_capital_pct,
			doc.supplier_financing_rate_pct or config.supplier_financing_rate_pct,
		)
		result["layer3"] = layer3

	return result


@frappe.whitelist()
def check_rate_conflict(
	item: str, supplier: str, city: str, valid_from: str, valid_to: str = None, exclude_name: str = None
):
	if not frappe.has_permission("Material Rate", "write"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	filters = {"item": item, "supplier": supplier, "city": city, "docstatus": 1}
	if exclude_name:
		filters["name"] = ["!=", exclude_name]

	existing = frappe.get_all(
		"Material Rate",
		filters=filters,
		fields=["name", "valid_from", "valid_to"],
	)

	from frappe.utils import getdate
	vf = getdate(valid_from)
	vt = getdate(valid_to) if valid_to else None
	far_future = getdate(frappe.utils.add_years(now_datetime(), 100))
	vt_cmp = vt if vt else far_future

	conflicts = []
	for e in existing:
		et_cmp = getdate(e.valid_to) if e.valid_to else far_future
		ef = getdate(e.valid_from)
		if ef < vt_cmp and et_cmp > vf:
			conflicts.append({"name": e.name, "valid_from": str(e.valid_from), "valid_to": str(e.valid_to)})

	return {"has_conflict": bool(conflicts), "conflicts": conflicts}


@frappe.whitelist()
def auto_expire_rate(rate_name: str, new_valid_to: str):
	if not frappe.has_permission("Material Rate", "write"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	frappe.db.set_value("Material Rate", rate_name, "valid_to", new_valid_to)
	return {"success": True}


def on_material_rate_submitted(doc, method):
	"""Hook: fires on_submit of Material Rate. Synchronously re-evaluate all affected PCs."""
	from mpd_customizations.costing.services.config import get_config
	from mpd_customizations.costing.services.rate_source_registry import get_default_registry
	from mpd_customizations.costing.services.costing_engine import CostingEngine

	open_calcs = frappe.get_all(
		"Pricing Calculation",
		filters={"mode": ["in", ["Awaiting Rates", "Ready for Working"]]},
		fields=["name", "owner"],
	)
	if not open_calcs:
		return

	for pc in open_calcs:
		has_relevant = frappe.db.exists(
			"Costing Rate Line",
			{"parent": pc.name, "item": doc.item, "rate_freshness": ["in", ["Missing", "Expired"]]},
		)
		if not has_relevant:
			continue
		try:
			CostingEngine(get_default_registry(), get_config()).evaluate(pc.name, "auto")
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"Auto-evaluate failed for {pc.name}")
			continue
		frappe.publish_realtime(
			"eval_js",
			f"if(cur_frm&&cur_frm.doctype==='Pricing Calculation'&&cur_frm.docname==='{pc.name}'){{cur_frm.reload_doc();frappe.show_alert({{message:'Rates updated — calculation refreshed',indicator:'green'}});}}",
			user=pc.owner,
		)


@frappe.whitelist()
def approve_pricing_calculation(pricing_calculation_name: str):
	if not set(frappe.get_roles()) & {"Costing Approver", "System Manager"}:
		frappe.throw(_("Only Costing Approvers can approve."), frappe.PermissionError)

	pc = frappe.get_doc("Pricing Calculation", pricing_calculation_name)
	pc.mode = "Approved"
	pc.submit()  # sets docstatus=1, fires before_submit validation

	if pc.pricing_request:
		frappe.db.set_value("Pricing Request", pc.pricing_request, "status", "Approved")
		pr_docstatus = frappe.db.get_value("Pricing Request", pc.pricing_request, "docstatus")
		if pr_docstatus == 0:
			frappe.db.set_value("Pricing Request", pc.pricing_request, "docstatus", 1)

	if not pc.valid_until:
		pc.valid_until = frappe.utils.add_days(frappe.utils.today(), QUOTE_VALIDITY_DAYS)
		frappe.db.set_value("Pricing Calculation", pc.name, "valid_until", pc.valid_until)

	_upsert_standard_costed_price(pc)

	return {"success": True}


def _upsert_standard_costed_price(pc):
	if not frappe.db.exists("Price List", STANDARD_COSTED_PRICE_LIST):
		return

	rate = pc.confirmed_ex_factory_cost_per_kg
	if not rate:
		return

	uom = frappe.db.get_value("Item", pc.item, "stock_uom") or "Kg"
	valid_from = frappe.utils.today()
	valid_upto = pc.valid_until

	existing = frappe.db.get_value(
		"Item Price",
		{"item_code": pc.item, "price_list": STANDARD_COSTED_PRICE_LIST, "uom": uom},
		"name",
	)

	if existing:
		frappe.db.set_value("Item Price", existing, {
			"price_list_rate": rate,
			"valid_from": valid_from,
			"valid_upto": valid_upto,
			"reference": pc.name,
		})
	else:
		frappe.get_doc({
			"doctype": "Item Price",
			"item_code": pc.item,
			"price_list": STANDARD_COSTED_PRICE_LIST,
			"uom": uom,
			"price_list_rate": rate,
			"valid_from": valid_from,
			"valid_upto": valid_upto,
			"reference": pc.name,
		}).insert(ignore_permissions=True)


@frappe.whitelist()
def reject_pricing_calculation(pricing_calculation_name: str):
	if not set(frappe.get_roles()) & {"Costing Approver", "System Manager"}:
		frappe.throw(_("Only Costing Approvers can reject."), frappe.PermissionError)

	pc = frappe.get_doc("Pricing Calculation", pricing_calculation_name)
	frappe.db.set_value("Pricing Calculation", pricing_calculation_name, "mode", "Rejected")

	if pc.pricing_request:
		frappe.db.set_value("Pricing Request", pc.pricing_request, "status", "Rejected")

	return {"success": True}


@frappe.whitelist()
def fetch_processing_charge(pricing_calculation_name: str):
	frappe.has_permission("Pricing Calculation", "write", throw=True)

	from mpd_customizations.costing.services.rate_fetcher import _get_processing_charge

	doc = frappe.get_doc("Pricing Calculation", pricing_calculation_name)
	if not doc.processor or not doc.item:
		return None

	pc = _get_processing_charge(doc.processor, doc.item, now_datetime())
	if not pc:
		return None

	existing_pl = doc.processing_lines[0] if doc.processing_lines else None
	if existing_pl:
		existing_pl.fetched_charge_per_kg = pc["charge_per_kg"]
		existing_pl.fetched_freight_per_unit = pc.get("fg_freight_per_unit") or 0
		existing_pl.fetched_includes_outward_freight = pc.get("includes_outward_freight")
		existing_pl.working_charge_per_kg = pc["charge_per_kg"]
		existing_pl.working_freight_per_unit = pc.get("fg_freight_per_unit") or 0
		existing_pl.working_includes_outward_freight = pc.get("includes_outward_freight")
		existing_pl.processing_charge_ref = pc["name"]
		existing_pl.processor = doc.processor
	else:
		doc.append("processing_lines", {
			"processor": doc.processor,
			"processing_charge_ref": pc["name"],
			"fetched_charge_per_kg": pc["charge_per_kg"],
			"fetched_freight_per_unit": pc.get("fg_freight_per_unit") or 0,
			"fetched_includes_outward_freight": pc.get("includes_outward_freight"),
			"working_charge_per_kg": pc["charge_per_kg"],
			"working_freight_per_unit": pc.get("fg_freight_per_unit") or 0,
			"working_includes_outward_freight": pc.get("includes_outward_freight"),
		})

	doc.save(ignore_permissions=True)
	return {"charge_per_kg": pc["charge_per_kg"], "ref": pc["name"]}


import frappe
from frappe import _
from frappe.utils import now_datetime

from mpd_customizations.costing.services.config import get_config
from mpd_customizations.costing.services.cost_calculator import (
	compute_additional_charge_amount,
	compute_financing_cost_for_line,
	compute_internal_earnings,
	compute_processing_cost,
	compute_rm_line_amount,
	compute_total_cost,
)
from mpd_customizations.costing.services.formulation_selector import FormulationSelector
from mpd_customizations.costing.services.rate_source_registry import get_default_registry


def _require_role(*roles):
	if not frappe.has_permission("Costing Request", "read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)


@frappe.whitelist()
def evaluate(costing_request_name: str, trigger: str = "manual"):
	frappe.has_permission("Costing Request", "write", throw=True)

	config = get_config()
	registry = get_default_registry()

	from mpd_customizations.costing.services.costing_engine import CostingEngine
	engine = CostingEngine(registry, config)
	return engine.evaluate(costing_request_name, trigger)


@frappe.whitelist()
def get_combinations(costing_request_name: str):
	frappe.has_permission("Costing Request", "read", throw=True)

	combos = frappe.get_all(
		"Costing Combination",
		filters={"costing_request": costing_request_name},
		fields=[
			"name", "bom", "formulation_id", "rank", "delta_pct", "status",
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
				"amount_per_kg", "financing_cost_per_kg", "confidence_score",
			],
		)
		ml_map = {}
		for ml in material_lines:
			ml_map.setdefault(ml.combination, []).append(ml)

		for combo in combos:
			combo["material_lines"] = ml_map.get(combo.name, [])

	return combos


@frappe.whitelist()
def select_combination(costing_request_name: str, combination_name: str):
	frappe.has_permission("Costing Request", "write", throw=True)

	frappe.db.set_value("Costing Combination", {"costing_request": costing_request_name}, "is_selected", 0)
	combo = frappe.get_doc("Costing Combination", combination_name)
	frappe.db.set_value("Costing Combination", combination_name, "is_selected", 1)

	doc = frappe.get_doc("Costing Request", costing_request_name)
	new_mode = "Ready to Quote" if combo.status in ("Ready to Quote", "Indicative — Rates Expired") else doc.mode
	frappe.db.set_value(
		"Costing Request",
		costing_request_name,
		{
			"selected_combination": combination_name,
			"confirmed_ex_factory_cost_per_kg": combo.total_cost_per_kg,
			"mode": new_mode,
		},
	)
	return {"confirmed_ex_factory_cost_per_kg": combo.total_cost_per_kg, "mode": new_mode}


@frappe.whitelist()
def apply_rate_override(
	costing_request_name: str,
	item: str,
	working_rate: float,
	working_supplier_credit_days: int,
	reason: str = "",
):
	frappe.has_permission("Costing Request", "write", throw=True)

	doc = frappe.get_doc("Costing Request", costing_request_name)
	for rl in doc.rate_lines:
		if rl.item == item:
			rl.working_rate = float(working_rate)
			rl.working_supplier_credit_days = int(working_supplier_credit_days)
			rl.override_reason = reason
			break

	doc.save(ignore_permissions=True)
	return _recompute_combinations(doc)


@frappe.whitelist()
def apply_processing_override(
	costing_request_name: str,
	working_charge_per_kg: float,
	working_freight_per_unit: float,
	working_includes_outward_freight: int,
	reason: str = "",
):
	frappe.has_permission("Costing Request", "write", throw=True)

	doc = frappe.get_doc("Costing Request", costing_request_name)
	if doc.processing_lines:
		pl = doc.processing_lines[0]
		pl.working_charge_per_kg = float(working_charge_per_kg)
		pl.working_freight_per_unit = float(working_freight_per_unit)
		pl.working_includes_outward_freight = int(working_includes_outward_freight)
		pl.override_reason = reason

	doc.save(ignore_permissions=True)
	return _recompute_combinations(doc)


@frappe.whitelist()
def revert_rate_override(costing_request_name: str, item: str):
	frappe.has_permission("Costing Request", "write", throw=True)

	doc = frappe.get_doc("Costing Request", costing_request_name)
	for rl in doc.rate_lines:
		if rl.item == item:
			rl.working_rate = rl.fetched_rate
			rl.working_supplier_credit_days = rl.fetched_supplier_credit_days
			rl.override_reason = ""
			break

	doc.save(ignore_permissions=True)
	return _recompute_combinations(doc)


@frappe.whitelist()
def revert_all_overrides(costing_request_name: str):
	frappe.has_permission("Costing Request", "write", throw=True)

	doc = frappe.get_doc("Costing Request", costing_request_name)
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
	return _recompute_combinations(doc)


@frappe.whitelist()
def create_pending_rates(costing_request_name: str):
	frappe.has_permission("Costing Request", "write", throw=True)

	doc = frappe.get_doc("Costing Request", costing_request_name)
	city = frappe.db.get_value("Processor", doc.processor, "city")
	created = []

	for rl in doc.rate_lines:
		if rl.rate_freshness in ("Missing", "Expired"):
			existing_pending = frappe.db.exists(
				"Material Rate",
				{"item": rl.item, "city": city, "docstatus": 0},
			)
			if not existing_pending:
				mr = frappe.get_doc({
					"doctype": "Material Rate",
					"item": rl.item,
					"city": city,
					"rate_type": "All-In Delivered",
					"valid_from": frappe.utils.today(),
					"uom": rl.uom or "Kg",
					"credit_days": 0,
				})
				mr.insert(ignore_permissions=True)
				created.append(mr.name)

	return {"created_count": len(created), "names": created}


@frappe.whitelist()
def get_previous_costing(item: str):
	frappe.has_permission("Costing Request", "read", throw=True)

	cr = frappe.get_all(
		"Costing Request",
		filters={"item": item, "mode": "Approved", "docstatus": 1},
		fields=[
			"name", "preferred_bom", "production_days", "supplier_financing_rate_pct",
			"confirmed_ex_factory_cost_per_kg",
		],
		order_by="modified desc",
		limit=1,
	)
	if not cr:
		return None

	prev = cr[0]
	additional_charges = frappe.get_all(
		"Costing Additional Charge",
		filters={"parent": prev.name},
		fields=["description", "basis", "rate"],
	)
	prev["additional_charges"] = additional_charges
	return prev


@frappe.whitelist()
def get_cost_breakdown(costing_request_name: str):
	frappe.has_permission("Costing Request", "read", throw=True)

	doc = frappe.get_doc("Costing Request", costing_request_name)
	if not doc.selected_combination:
		return {}

	combo = frappe.get_doc("Costing Combination", doc.selected_combination)
	material_lines = frappe.get_all(
		"Costing Material Line",
		filters={"combination": doc.selected_combination},
		fields=[
			"item", "item_name", "uom", "qty_per_kg_output", "supplier",
			"rate_freshness", "working_rate", "working_supplier_credit_days",
			"net_financed_days", "amount_per_kg", "financing_cost_per_kg",
		],
	)

	rate_lines_map = {rl.item: rl for rl in (doc.rate_lines or [])}
	for ml in material_lines:
		rl = rate_lines_map.get(ml.item)
		ml["fetched_rate"] = rl.fetched_rate if rl else None
		ml["is_overridden"] = (
			round(rl.working_rate or 0, 2) != round(rl.fetched_rate or 0, 2) if rl else False
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

	# Layer 3 — only for Costing Approver and System Manager
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

	from frappe.utils import get_datetime
	from mpd_customizations.costing.services.rate_source_registry import get_default_registry

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
	"""Hook: fires on_submit of Material Rate. Notify CR owners where this fills a gap."""
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
			{"parent": cr.name, "item": doc.item, "rate_freshness": ["in", ["Missing", "Expired"]]},
		)
		if has_missing:
			frappe.sendmail(
				recipients=[cr.owner],
				subject=f"New rate added for {doc.item_name or doc.item} — {city}",
				message=(
					f"A new rate for <b>{doc.item_name or doc.item}</b> in {city} has been added "
					f"by {frappe.session.user}.<br>You may now re-evaluate "
					f"<a href='/app/costing-request/{cr.name}'>{cr.name}</a>."
				),
			)


def _recompute_combinations(doc) -> dict:
	"""After an override update, recompute all combination costs and re-rank."""
	config = get_config()
	production_days = doc.production_days or 30
	financing_rate = doc.supplier_financing_rate_pct or 12.0
	solids = doc.solids_content_pct or 0
	rate_lines_map = {rl.item: rl for rl in (doc.rate_lines or [])}
	processing_line = doc.processing_lines[0] if doc.processing_lines else None

	additional_charges_per_kg = sum(
		compute_additional_charge_amount(c.rate or 0, c.basis, solids)
		for c in (doc.additional_charges or [])
	)

	combos = frappe.get_all(
		"Costing Combination",
		filters={"costing_request": doc.name},
		fields=["name", "bom"],
	)

	combination_totals = []
	for combo in combos:
		material_lines = frappe.get_all(
			"Costing Material Line",
			filters={"combination": combo.name},
			fields=["item", "item_name", "qty_per_kg_output", "rate_freshness", "net_financed_days"],
		)

		rm_cost = 0.0
		financing_cost = 0.0
		missing_items = []
		expired_items = []

		for ml in material_lines:
			rl = rate_lines_map.get(ml.item)
			working_rate = (rl.working_rate or 0) if rl else 0.0
			credit_days = (rl.working_supplier_credit_days or 0) if rl else 0
			freshness = (rl.rate_freshness or "Missing") if rl else "Missing"
			net_financed = max(0, production_days - credit_days)

			amount = compute_rm_line_amount(ml.qty_per_kg_output or 0, working_rate)
			fin = compute_financing_cost_for_line(amount, production_days, credit_days, financing_rate)
			rm_cost += amount
			financing_cost += fin

			frappe.db.set_value(
				"Costing Material Line",
				{"combination": combo.name, "item": ml.item},
				{
					"working_rate": working_rate,
					"working_supplier_credit_days": credit_days,
					"net_financed_days": net_financed,
					"amount_per_kg": amount,
					"financing_cost_per_kg": fin,
					"rate_freshness": freshness,
				},
			)

			if freshness == "Missing":
				missing_items.append(ml.item)
			elif freshness == "Expired":
				expired_items.append(ml.item)

		processing_cost = 0.0
		outward_freight = 0.0
		if processing_line:
			processing_cost = compute_processing_cost(solids, processing_line.working_charge_per_kg or 0)
			if not processing_line.working_includes_outward_freight:
				outward_freight = processing_line.working_freight_per_unit or 0

		total = compute_total_cost(rm_cost, financing_cost, processing_cost, additional_charges_per_kg, outward_freight)

		if missing_items:
			status = "Indicative — Rates Missing"
		elif expired_items:
			status = "Indicative — Rates Expired"
		else:
			status = "Ready to Quote"

		combination_totals.append({
			"name": combo.name,
			"bom": combo.bom,
			"rm_cost_per_kg": rm_cost,
			"financing_cost_per_kg": financing_cost,
			"processing_cost_per_kg": processing_cost,
			"additional_charges_per_kg": additional_charges_per_kg,
			"outward_freight_per_kg": outward_freight,
			"total_cost_per_kg": total,
			"status": status,
			"missing_items": ", ".join(missing_items),
			"expired_items": ", ".join(expired_items),
		})

	selector = FormulationSelector(config)
	selection = selector.select(
		[dict(c) for c in combination_totals], doc.preferred_bom
	)

	for combo_data in combination_totals:
		frappe.db.set_value(
			"Costing Combination",
			combo_data["name"],
			{
				"rm_cost_per_kg": combo_data["rm_cost_per_kg"],
				"financing_cost_per_kg": combo_data["financing_cost_per_kg"],
				"processing_cost_per_kg": combo_data["processing_cost_per_kg"],
				"additional_charges_per_kg": combo_data["additional_charges_per_kg"],
				"outward_freight_per_kg": combo_data["outward_freight_per_kg"],
				"total_cost_per_kg": combo_data["total_cost_per_kg"],
				"status": combo_data["status"],
				"rank": combo_data.get("rank") or 1,
				"delta_pct": combo_data.get("delta_pct", 0),
				"missing_items": combo_data["missing_items"],
				"expired_items": combo_data["expired_items"],
			},
		)

	if doc.selected_combination:
		selected = next((c for c in combination_totals if c["name"] == doc.selected_combination), None)
		if selected:
			frappe.db.set_value(
				"Costing Request",
				doc.name,
				"confirmed_ex_factory_cost_per_kg",
				selected["total_cost_per_kg"],
			)

	frappe.db.set_value(
		"Costing Request",
		doc.name,
		"formulation_switch_alert",
		selection.switch_alert or "",
	)

	return {
		"combinations": combination_totals,
		"switch_alert": selection.switch_alert,
	}

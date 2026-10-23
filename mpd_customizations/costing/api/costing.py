import frappe
from frappe import _
from frappe.utils import now_datetime

from mpd_customizations.costing.services.config import get_config
from mpd_customizations.costing.services.pricing_workflow import (
	approve_customer_product as _approve_customer_product,
)
from mpd_customizations.costing.services.pricing_workflow import (
	approve_pricing_calculation as _approve_pricing_calculation,
)
from mpd_customizations.costing.services.pricing_workflow import (
	check_rate_conflict as _check_rate_conflict,
)
from mpd_customizations.costing.services.pricing_workflow import (
	reject_pricing_calculation as _reject_pricing_calculation,
)
from mpd_customizations.costing.services.pricing_workflow import (
	select_combination as _select_combination,
)
from mpd_customizations.costing.services.rate_source_registry import get_default_registry


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
	raw = frappe.db.get_value("Pricing Calculation", pricing_calculation_name, "costing_raw")
	return frappe.parse_json(raw or "{}").get("combinations", [])


@frappe.whitelist()
def select_combination(pricing_calculation_name: str, bom: str):
	frappe.has_permission("Pricing Calculation", "write", throw=True)
	return _select_combination(pricing_calculation_name, bom)


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
	return {"saved": True}


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
	return {"saved": True}


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
	return {"saved": True}


_PARAM_MAP = {
	"production_days": "fetched_production_days",
	"supplier_financing_rate_pct": "fetched_supplier_financing_rate_pct",
	"customer_credit_rate_pct": "fetched_customer_credit_rate_pct",
}


@frappe.whitelist()
def revert_parameter_override(pricing_calculation_name: str, param_name: str):
	frappe.has_permission("Pricing Calculation", "write", throw=True)
	fetched_field = _PARAM_MAP.get(param_name)
	if not fetched_field:
		frappe.throw(_("Unknown parameter: {0}").format(param_name))
	val = frappe.db.get_value("Pricing Calculation", pricing_calculation_name, fetched_field)
	frappe.db.set_value("Pricing Calculation", pricing_calculation_name, param_name, val)
	return {"saved": True}


@frappe.whitelist()
def revert_freight_override(pricing_calculation_name: str, row_name: str):
	frappe.has_permission("Pricing Calculation", "write", throw=True)
	doc = frappe.get_doc("Pricing Calculation", pricing_calculation_name)
	for dl in doc.delivery_lines:
		if dl.name == row_name:
			dl.working_freight_per_kg = dl.fetched_freight_per_kg or 0
			break
	doc.save(ignore_permissions=True)
	return {"saved": True}


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

	for dl in doc.delivery_lines:
		if dl.fetched_freight_per_kg is not None:
			dl.working_freight_per_kg = dl.fetched_freight_per_kg

	doc.save(ignore_permissions=True)

	for param, fetched_field in _PARAM_MAP.items():
		fetched_val = frappe.db.get_value("Pricing Calculation", pricing_calculation_name, fetched_field)
		if fetched_val is not None:
			frappe.db.set_value("Pricing Calculation", pricing_calculation_name, param, fetched_val)

	return {"saved": True}


@frappe.whitelist()
def check_rate_conflict(
	item: str, supplier: str, city: str, valid_from: str, valid_to: str = None, exclude_name: str = None
):
	if not frappe.has_permission("Material Rate", "write"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	return _check_rate_conflict(item, supplier, city, valid_from, valid_to, exclude_name)


@frappe.whitelist()
def auto_expire_rate(rate_name: str, new_valid_to: str):
	if not frappe.has_permission("Material Rate", "write"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	frappe.db.set_value("Material Rate", rate_name, "valid_to", new_valid_to)
	return {"success": True}


@frappe.whitelist()
def approve_customer_product(name: str):
	if not set(frappe.get_roles()) & {"Costing Approver", "System Manager"}:
		frappe.throw(_("Only Costing Approvers can approve."), frappe.PermissionError)
	return _approve_customer_product(name)


@frappe.whitelist()
def approve_pricing_calculation(pricing_calculation_name: str):
	if not set(frappe.get_roles()) & {"Costing Approver", "System Manager"}:
		frappe.throw(_("Only Costing Approvers can approve."), frappe.PermissionError)
	return _approve_pricing_calculation(pricing_calculation_name)


@frappe.whitelist()
def reject_pricing_calculation(pricing_calculation_name: str):
	if not set(frappe.get_roles()) & {"Costing Approver", "System Manager"}:
		frappe.throw(_("Only Costing Approvers can reject."), frappe.PermissionError)
	return _reject_pricing_calculation(pricing_calculation_name)


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
		doc.append(
			"processing_lines",
			{
				"processor": doc.processor,
				"processing_charge_ref": pc["name"],
				"fetched_charge_per_kg": pc["charge_per_kg"],
				"fetched_freight_per_unit": pc.get("fg_freight_per_unit") or 0,
				"fetched_includes_outward_freight": pc.get("includes_outward_freight"),
				"working_charge_per_kg": pc["charge_per_kg"],
				"working_freight_per_unit": pc.get("fg_freight_per_unit") or 0,
				"working_includes_outward_freight": pc.get("includes_outward_freight"),
			},
		)

	doc.save(ignore_permissions=True)
	return {"charge_per_kg": pc["charge_per_kg"], "ref": pc["name"]}

import json

import frappe

from mpd_customizations.xfloor_costing.services.pl_engine import (
	build_comparison,
	calc_project as calc_project_service,
	get_kit_rates_doc,
)


ALLOWED_ROLES = frozenset({"System Manager", "XFloor Costing Manager"})


def _user_roles():
	return set(frappe.get_roles())


def _ensure_access():
	if frappe.session.user == "Administrator":
		return
	if _user_roles() & ALLOWED_ROLES:
		return
	frappe.throw("Not permitted", frappe.PermissionError)


def _ensure_rates_write():
	if frappe.session.user == "Administrator":
		return
	if "System Manager" in _user_roles():
		return
	frappe.throw("Only System Managers can edit kit rates.", frappe.PermissionError)


@frappe.whitelist()
def get_dashboard():
	_ensure_access()
	projects = frappe.get_all(
		"Floor Project",
		fields=[
			"name",
			"project_number",
			"party_name",
			"sqft",
			"contract_value",
			"total_cost",
			"profit_loss",
			"margin_pct",
			"status",
		],
		order_by="modified desc",
	)
	totals = {
		"contract_value": sum(float(p.get("contract_value") or 0) for p in projects),
		"total_cost": sum(float(p.get("total_cost") or 0) for p in projects),
		"profit_loss": sum(float(p.get("profit_loss") or 0) for p in projects),
	}
	return {
		"projects": projects,
		"totals": totals,
		"kit_rates": get_kit_rates(),
		"kit_coverage": get_kit_coverage(),
		"can_edit_rates": _can_edit_rates(),
		"can_view_rates": True,
	}


def _can_edit_rates():
	return frappe.session.user == "Administrator" or "System Manager" in _user_roles()


@frappe.whitelist()
def get_project(name):
	_ensure_access()
	doc = frappe.get_doc("Floor Project", name)
	project = doc.as_dict()
	project["dispatch_lines"] = [d.as_dict() for d in doc.dispatch_lines]
	project["budget_rows"] = doc.get_budget_rows()
	project["comparison"] = doc.get_comparison_rows()
	return project


@frappe.whitelist()
def save_project(doc):
	_ensure_access()
	payload = frappe.parse_json(doc) if isinstance(doc, str) else (doc or {})
	name = payload.get("name")
	if name:
		project = frappe.get_doc("Floor Project", name)
		dispatch_lines = payload.pop("dispatch_lines", None)
		project.update(payload)
		if dispatch_lines is not None:
			project.set("dispatch_lines", [])
			for row in dispatch_lines:
				project.append("dispatch_lines", row)
	else:
		project = frappe.new_doc("Floor Project")
		dispatch_lines = payload.pop("dispatch_lines", None)
		project.update(payload)
		if dispatch_lines is not None:
			for row in dispatch_lines:
				project.append("dispatch_lines", row)
	project.save(ignore_permissions=True)
	result = project.as_dict()
	result["budget_rows"] = project.get_budget_rows()
	result["comparison"] = project.get_comparison_rows()
	result["dispatch_lines"] = [d.as_dict() for d in project.dispatch_lines]
	return result


@frappe.whitelist()
def delete_project(name):
	_ensure_access()
	frappe.delete_doc("Floor Project", name, ignore_permissions=True)
	return {"ok": True}


@frappe.whitelist()
def get_kit_rates():
	_ensure_access()
	doc = frappe.get_single("Kit rates")
	data = doc.as_dict()
	data["rate_revisions"] = [r.as_dict() for r in doc.rate_revisions]
	return data


@frappe.whitelist()
def get_kit_coverage():
	_ensure_access()
	doc = frappe.get_single("Kit Coverage")
	data = doc.as_dict()
	data["coverage_revisions"] = [r.as_dict() for r in doc.coverage_revisions]
	return data


@frappe.whitelist()
def save_kit_rates(data):
	_ensure_rates_write()
	payload = frappe.parse_json(data) if isinstance(data, str) else (data or {})
	doc = frappe.get_single("Kit rates")
	doc.update(payload)
	doc.save()
	return {"ok": True}


@frappe.whitelist()
def save_kit_coverage(data):
	_ensure_access()
	payload = frappe.parse_json(data) if isinstance(data, str) else (data or {})
	doc = frappe.get_single("Kit Coverage")
	doc.update(payload)
	doc.save()
	return {"ok": True}


@frappe.whitelist()
def calc_project(data):
	_ensure_access()
	payload = frappe.parse_json(data) if isinstance(data, str) else (data or {})
	if not isinstance(payload, dict):
		payload = dict(payload)
	result = calc_project_service(payload)
	result["comparison"] = build_comparison(result["budget_rows"], payload.get("dispatch_lines") or [])
	return result


@frappe.whitelist()
def export_pdf(name):
	_ensure_access()
	doc = frappe.get_doc("Floor Project", name)
	return {
		"project": doc.as_dict(),
		"budget": json.loads(doc.budget_json or "[]"),
		"comparison": json.loads(doc.comparison_json or "[]"),
		"settings": get_kit_rates_doc(),
	}

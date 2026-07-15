import frappe

from mpd_customizations.xfloor_costing.services.pl_engine import (
	build_comparison,
	calc_project as calc_project_service,
	get_kit_rates_doc,
	strip_gm_from_kit_rates,
	strip_gm_from_result,
)


ALLOWED_ROLES = frozenset({"System Manager", "XFloor Costing Manager"})


def _user_roles():
	return set(frappe.get_roles())


def _is_system_manager():
	if frappe.session.user == "Administrator":
		return True
	return "System Manager" in _user_roles()


def _ensure_access():
	if frappe.session.user == "Administrator":
		return
	if _user_roles() & ALLOWED_ROLES:
		return
	frappe.throw("Not permitted", frappe.PermissionError)


def _ensure_rates_write():
	if _is_system_manager():
		return
	frappe.throw("Only System Managers can edit kit rates.", frappe.PermissionError)


def _ensure_coverage_write():
	if _is_system_manager():
		return
	frappe.throw("Only System Managers can edit kit coverage.", frappe.PermissionError)


def _maybe_strip_result(result):
	if _is_system_manager():
		return result
	return strip_gm_from_result(result)


def _attach_live_profiles(project_dict):
	"""Attach live cost_profile (all roles) and margin_summary (SM only)."""
	calc = calc_project_service(project_dict)
	project_dict["cost_profile"] = calc.get("cost_profile")

	if not _is_system_manager():
		project_dict.pop("margin_summary", None)
		return project_dict

	project_dict["margin_summary"] = calc.get("margin_summary")
	# Enrich budget / part rows with live GM for Margin tab without changing stored JSON.
	by_name = {r.get("component"): r for r in (calc.get("budget_rows") or [])}
	enriched = []
	for row in project_dict.get("budget_rows") or []:
		item = dict(row)
		src = by_name.get(item.get("component")) or {}
		item["gm_per_kit"] = src.get("gm_per_kit", 0)
		item["gm_amount"] = src.get("gm_amount", 0)
		enriched.append(item)
	project_dict["budget_rows"] = enriched

	calc_parts = calc.get("part_budgets") or []
	out_parts = []
	for idx, part in enumerate(project_dict.get("part_budgets") or []):
		p = dict(part)
		src_part = calc_parts[idx] if idx < len(calc_parts) else {}
		src_by = {r.get("component"): r for r in (src_part.get("budget_rows") or [])}
		p_rows = []
		for row in p.get("budget_rows") or []:
			item = dict(row)
			src = src_by.get(item.get("component")) or {}
			item["gm_per_kit"] = src.get("gm_per_kit", 0)
			item["gm_amount"] = src.get("gm_amount", 0)
			p_rows.append(item)
		p["budget_rows"] = p_rows
		out_parts.append(p)
	project_dict["part_budgets"] = out_parts
	return project_dict


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
		"can_edit_rates": _is_system_manager(),
		"can_view_rates": True,
		"can_view_margin": _is_system_manager(),
		"can_view_cost_profile": True,
	}


def _project_response(project):
	result = project.as_dict()
	result["budget_rows"] = project.get_budget_rows()
	result["part_budgets"] = project.get_part_budgets()
	result["comparison"] = project.get_comparison_rows()
	result["dispatch_lines"] = [d.as_dict() for d in project.dispatch_lines]
	result["parts"] = [p.as_dict() for p in project.parts]

	result = _attach_live_profiles(result)

	if _is_system_manager():
		return result

	stripped = strip_gm_from_result(
		{
			"budget_rows": result["budget_rows"],
			"part_budgets": result["part_budgets"],
			"cost_profile": result.get("cost_profile"),
		}
	)
	result["budget_rows"] = stripped["budget_rows"]
	result["part_budgets"] = stripped["part_budgets"]
	result["cost_profile"] = stripped.get("cost_profile") or result.get("cost_profile")
	result.pop("margin_summary", None)
	return result


def _apply_child_table(project, payload, fieldname):
	rows = payload.pop(fieldname, None)
	if rows is None:
		return
	project.set(fieldname, [])
	for row in rows:
		project.append(fieldname, row)


@frappe.whitelist()
def get_project(name):
	_ensure_access()
	doc = frappe.get_doc("Floor Project", name)
	return _project_response(doc)


@frappe.whitelist()
def save_project(doc):
	_ensure_access()
	payload = frappe.parse_json(doc) if isinstance(doc, str) else (doc or {})
	name = payload.get("name")
	if name:
		project = frappe.get_doc("Floor Project", name)
		_apply_child_table(project, payload, "dispatch_lines")
		_apply_child_table(project, payload, "parts")
		project.update(payload)
	else:
		project = frappe.new_doc("Floor Project")
		_apply_child_table(project, payload, "dispatch_lines")
		_apply_child_table(project, payload, "parts")
		project.update(payload)
	project.save(ignore_permissions=True)
	return _project_response(project)


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
	if not _is_system_manager():
		data = strip_gm_from_kit_rates(data)
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
	_ensure_coverage_write()
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
	return _maybe_strip_result(result)


@frappe.whitelist()
def export_pdf(name):
	_ensure_access()
	doc = frappe.get_doc("Floor Project", name)
	settings = get_kit_rates_doc()
	if not _is_system_manager():
		settings = strip_gm_from_kit_rates(settings)
	return {
		"project": doc.as_dict(),
		"budget": doc.get_budget_rows(),
		"part_budgets": doc.get_part_budgets(),
		"comparison": doc.get_comparison_rows(),
		"settings": settings,
	}

"""Writes for the register, activities, and context documents."""

import frappe

from mpd_customizations.compliance.services.access import require_activity_write, require_manager
from mpd_customizations.compliance.services.generate import extend_due
from mpd_customizations.compliance.services.workflow import apply_action


def _via(doc):
	if frappe.flags.get("compliance_via_mcp"):
		doc.add_comment("Comment", f"via MCP by {frappe.session.user}")


@frappe.whitelist()
def add_activity(**kwargs):
	data = _clean(kwargs)
	data["doctype"] = "Compliance Activity"
	data.setdefault("source", "Agent" if frappe.flags.get("compliance_via_mcp") else "Manual")
	data.setdefault("status", "Not Started")
	doc = frappe.get_doc(data)
	doc.insert()
	return {"name": doc.name, "url": f"/desk/compliance-activity/{doc.name}"}


@frappe.whitelist()
def update_activity(name, **kwargs):
	doc = frappe.get_doc("Compliance Activity", name)
	require_activity_write(doc)
	for key, value in _clean(kwargs).items():
		if key in ("name", "doctype", "task", "project"):
			continue
		doc.set(key, value)
	doc.save()
	return {"name": doc.name}


@frappe.whitelist()
def act(name, action, ack_no=None, amount_paid=None, na_reason=None, comment=None):
	doc = apply_action(
		name, action, ack_no=ack_no, amount_paid=amount_paid, na_reason=na_reason, comment=comment
	)
	return {"name": doc.name, "status": doc.status}


@frappe.whitelist()
def add_obligation(**kwargs):
	require_manager()
	data = _clean(kwargs)
	activate = str(data.pop("activate", "")).lower() in ("1", "true", "yes")
	data["doctype"] = "Compliance Obligation"
	data.setdefault("status", "Active" if activate else "Draft")
	data.setdefault("source", "Agent" if frappe.flags.get("compliance_via_mcp") else "Manual")
	doc = frappe.get_doc(data)
	doc.insert(ignore_permissions=True)
	_via(doc)
	return {"name": doc.name, "status": doc.status}


@frappe.whitelist()
def update_obligation(name, **kwargs):
	require_manager()
	doc = frappe.get_doc("Compliance Obligation", name)
	for key, value in _clean(kwargs).items():
		if key in ("name", "cmd"):
			continue
		doc.set(key, value)
	doc.save(ignore_permissions=True)
	return {"name": doc.name, "status": doc.status}


@frappe.whitelist()
def set_obligation_status(name, status):
	require_manager()
	if status not in ("Draft", "Active", "Inactive"):
		frappe.throw("Status must be Draft, Active, or Inactive.")
	doc = frappe.get_doc("Compliance Obligation", name)
	doc.status = status
	doc.save(ignore_permissions=True)
	return {"name": doc.name, "status": doc.status}


@frappe.whitelist()
def add_registration(**kwargs):
	require_manager()
	data = _clean(kwargs)
	data["doctype"] = "Compliance Registration"
	doc = frappe.get_doc(data)
	doc.insert(ignore_permissions=True)
	return {"name": doc.name}


@frappe.whitelist()
def update_registration(name, **kwargs):
	require_manager()
	doc = frappe.get_doc("Compliance Registration", name)
	for key, value in _clean(kwargs).items():
		doc.set(key, value)
	doc.save(ignore_permissions=True)
	return {"name": doc.name}


@frappe.whitelist()
def add_domain(domain_name, description=None):
	require_manager()
	if frappe.db.exists("Compliance Domain", domain_name):
		return {"name": domain_name}
	doc = frappe.get_doc(
		{"doctype": "Compliance Domain", "domain_name": domain_name, "description": description}
	)
	doc.insert(ignore_permissions=True)
	return {"name": doc.name}


@frappe.whitelist()
def add_site(location, company, parent_location=None, **facts):
	require_manager()
	if not frappe.db.exists("Location", location):
		frappe.get_doc(
			{
				"doctype": "Location",
				"location_name": location,
				"parent_location": parent_location,
				"is_group": 0,
			}
		).insert(ignore_permissions=True)
	existing = frappe.db.get_value("Compliance Site", {"location": location}, "name")
	if existing:
		return {"name": existing}
	doc = frappe.get_doc(
		{"doctype": "Compliance Site", "location": location, "company": company, **_clean(facts)}
	)
	doc.insert(ignore_permissions=True)
	return {"name": doc.name}


@frappe.whitelist()
def update_site(name, **kwargs):
	require_manager()
	doc = frappe.get_doc("Compliance Site", name)
	for key, value in _clean(kwargs).items():
		doc.set(key, value)
	doc.save(ignore_permissions=True)
	return {"name": doc.name}


@frappe.whitelist()
def update_company_profile(company, **kwargs):
	require_manager()
	name = frappe.db.get_value("Compliance Company Profile", {"company": company}, "name")
	if name:
		doc = frappe.get_doc("Compliance Company Profile", name)
	else:
		doc = frappe.new_doc("Compliance Company Profile")
		doc.company = company
	for key, value in _clean(kwargs).items():
		doc.set(key, value)
	if doc.is_new():
		doc.insert(ignore_permissions=True)
	else:
		doc.save(ignore_permissions=True)
	return {"name": doc.name}


@frappe.whitelist()
def move_due(new_date, reason, obligation=None, domain=None, period_label=None):
	require_manager()
	return extend_due(new_date, reason, obligation=obligation, domain=domain, period_label=period_label)


def _clean(kwargs):
	return {
		key: value
		for key, value in (kwargs or {}).items()
		if key not in ("cmd", "doctype") and value is not None
	}

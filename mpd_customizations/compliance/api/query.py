"""Read models for the compliance desk and MCP."""

import frappe
from frappe.utils import add_days, getdate

from mpd_customizations.compliance.services.access import has_permission, is_manager
from mpd_customizations.compliance.services.coverage import find_gaps


def _gate(doctype, name):
	doc = frappe.get_doc(doctype, name)
	if not has_permission(doc, "read"):
		frappe.throw(frappe._("Not permitted"), frappe.PermissionError)
	return doc


@frappe.whitelist()
def dashboard(company=None):
	today = getdate()
	activities = _visible_activities(company)
	open_rows = [row for row in activities if row.status not in ("Completed", "Not Applicable", "Waived")]
	completed = [row for row in activities if row.status == "Completed"]
	on_time = [row for row in completed if not row.days_late]
	return {
		"overdue": sum(1 for row in open_rows if row.is_overdue),
		"due_this_week": sum(
			1 for row in open_rows if row.due_date and today <= getdate(row.due_date) <= add_days(today, 7)
		),
		"pending_review": sum(1 for row in activities if row.status == "Pending Review"),
		"my_open": sum(1 for row in open_rows if row.responsible_user == frappe.session.user),
		"on_time_percent": round(100 * len(on_time) / len(completed), 1) if completed else None,
		"draft_obligations": frappe.db.count("Compliance Obligation", {"status": "Draft"}),
	}


@frappe.whitelist()
def list_activities(
	company=None,
	site=None,
	domain=None,
	status=None,
	owner=None,
	period=None,
	overdue=None,
	due_from=None,
	due_to=None,
):
	filters = {}
	if company:
		filters["company"] = company
	if site:
		filters["site"] = site
	if domain:
		filters["domain"] = domain
	if status:
		filters["status"] = status
	if owner:
		filters["responsible_user"] = owner
	if period:
		filters["period_label"] = period
	if str(overdue) in ("1", "true", "True"):
		filters["is_overdue"] = 1
	if due_from and due_to:
		filters["due_date"] = ["between", [due_from, due_to]]
	elif due_from:
		filters["due_date"] = [">=", due_from]
	elif due_to:
		filters["due_date"] = ["<=", due_to]
	rows = frappe.get_list(
		"Compliance Activity",
		filters=filters,
		fields=[
			"name",
			"title",
			"status",
			"domain",
			"company",
			"site",
			"period_label",
			"due_date",
			"is_overdue",
			"days_late",
			"responsible_user",
			"reviewer",
			"task",
			"obligation",
		],
		order_by="due_date asc",
		limit=200,
	)
	return {"activities": rows}


@frappe.whitelist()
def get_activity(name):
	doc = _gate("Compliance Activity", name)
	data = doc.as_dict()
	data["url"] = f"/desk/compliance-activity/{doc.name}"
	return {"activity": data}


@frappe.whitelist()
def get_obligation(name):
	doc = _gate("Compliance Obligation", name)
	return {"obligation": doc.as_dict()}


@frappe.whitelist()
def register(company=None, site=None, domain=None, status=None, source=None):
	filters = {}
	for key, value in (
		("company", company),
		("site", site),
		("domain", domain),
		("status", status),
		("source", source),
	):
		if value:
			filters[key] = value
	rows = frappe.get_list(
		"Compliance Obligation",
		filters=filters,
		fields=[
			"name",
			"title",
			"domain",
			"status",
			"scope",
			"company",
			"site",
			"frequency",
			"risk",
			"responsible_user",
			"source",
			"law_reference",
		],
		limit=300,
	)
	return {"obligations": rows}


@frappe.whitelist()
def list_registrations(company=None, site=None, expiring_within_days=None):
	filters = {}
	if company:
		filters["company"] = company
	if site:
		filters["site"] = site
	if expiring_within_days:
		filters["valid_to"] = ["between", [getdate(), add_days(getdate(), int(expiring_within_days))]]
		filters["status"] = "Active"
	rows = frappe.get_list(
		"Compliance Registration",
		filters=filters,
		fields=[
			"name",
			"registration_type",
			"registration_number",
			"company",
			"site",
			"status",
			"valid_to",
			"authority",
		],
		limit=300,
	)
	return {"registrations": rows}


@frappe.whitelist()
def context():
	companies = frappe.get_all("Company", fields=["name", "abbr"])
	profiles = frappe.get_all("Compliance Company Profile", fields=["*"])
	sites = frappe.get_all(
		"Compliance Site",
		fields=[
			"name",
			"location",
			"company",
			"site_type",
			"state",
			"direct_headcount",
			"contract_headcount",
			"has_boiler",
			"has_dg_set",
			"has_etp",
			"has_solvent_storage",
			"has_hazardous_chemicals",
			"has_food_pharma",
			"notes",
			"active",
		],
	)
	domains = frappe.get_all("Compliance Domain", fields=["name", "default_owner", "default_reviewer"])
	banks = []
	if frappe.db.exists("DocType", "Bank Account"):
		banks = frappe.get_all("Bank Account", fields=["name", "bank", "company"], limit=50)
	return {
		"companies": companies,
		"profiles": profiles,
		"sites": sites,
		"domains": domains,
		"banks": banks,
		"registrations": list_registrations().get("registrations"),
	}


@frappe.whitelist()
def coverage(company=None):
	registrations = frappe.get_all(
		"Compliance Registration",
		filters={"company": company} if company else None,
		fields=["name", "registration_type", "registration_number", "company", "site", "valid_to", "status"],
	)
	obligations = frappe.get_all(
		"Compliance Obligation",
		filters={"company": company} if company else None,
		fields=[
			"name",
			"title",
			"registration",
			"domain",
			"site",
			"company",
			"scope",
			"responsible_user",
			"frequency",
			"status",
		],
	)
	sites = frappe.get_all(
		"Compliance Site",
		filters={"company": company} if company else None,
		fields=["name", "location", "company", "active"],
	)
	activities = frappe.get_all(
		"Compliance Activity",
		filters={"company": company} if company else None,
		fields=[
			"name",
			"title",
			"obligation",
			"status",
			"evidence_required",
			"is_overdue",
			"period_label",
			"ack_no",
			"domain",
			"company",
		],
	)
	for row in activities:
		row["evidence_count"] = frappe.db.count(
			"Compliance Evidence", {"parent": row.name, "parenttype": "Compliance Activity"}
		)
	matrix = {}
	for row in obligations:
		if row.status != "Active":
			continue
		key = (row.company or "Group", row.site or "", row.domain)
		matrix.setdefault(key, 0)
		matrix[key] += 1
	return {
		"matrix": [
			{"company": key[0], "site": key[1], "domain": key[2], "obligations": count}
			for key, count in matrix.items()
		],
		"gaps": find_gaps(registrations, obligations, sites, activities, getdate()),
	}


@frappe.whitelist()
def unmatched():
	if not is_manager():
		frappe.throw(frappe._("Not permitted"), frappe.PermissionError)
	rows = frappe.get_all(
		"Compliance Unmatched Evidence",
		filters={"status": "Open"},
		fields=["name", "drive_file", "document_kind", "summary", "confidence"],
		limit=100,
	)
	return {"evidence": rows}


@frappe.whitelist()
def settings_view():
	doc = frappe.get_single("Compliance Settings")
	if not has_permission(doc, "read"):
		frappe.throw(frappe._("Not permitted"), frappe.PermissionError)
	return {"settings": doc.as_dict()}


def _visible_activities(company=None):
	filters = {"company": company} if company else {}
	return frappe.get_list(
		"Compliance Activity",
		filters=filters,
		fields=["name", "status", "due_date", "is_overdue", "days_late", "responsible_user"],
		limit=1000,
	)

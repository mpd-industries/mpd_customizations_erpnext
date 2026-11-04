"""Create one activity per obligation period. Idempotent on period label."""

import frappe
from frappe.utils import add_days, getdate

from mpd_customizations.compliance.services.schedule import occurrences
from mpd_customizations.compliance.services.status import overdue_flags


def generate_all(today=None):
	today = getdate(today or getdate())
	if not frappe.db.exists("DocType", "Compliance Obligation"):
		return 0
	ahead = 90
	if frappe.db.exists("Compliance Settings", "Compliance Settings"):
		ahead = int(frappe.db.get_single_value("Compliance Settings", "generate_ahead_days") or 90)
	window_end = add_days(today, ahead)
	created = 0
	for name in frappe.get_all("Compliance Obligation", filters={"status": "Active"}, pluck="name"):
		created += generate_for(name, today, window_end)
	return created


def generate_for(name, today=None, window_end=None):
	today = getdate(today or getdate())
	obligation = frappe.get_doc("Compliance Obligation", name)
	if obligation.status != "Active":
		return 0
	ahead = obligation.generate_ahead_days
	if not ahead and frappe.db.exists("Compliance Settings", "Compliance Settings"):
		ahead = frappe.db.get_single_value("Compliance Settings", "generate_ahead_days")
	window_end = getdate(window_end or add_days(today, int(ahead or 90)))
	window_start = add_days(today, -40)
	if obligation.effective_from and getdate(obligation.effective_from) > window_start:
		window_start = getdate(obligation.effective_from)
	valid_to = None
	if obligation.registration:
		valid_to = frappe.db.get_value("Compliance Registration", obligation.registration, "valid_to")
	rows = occurrences(_payload(obligation), window_start, window_end, valid_to=valid_to)
	created = 0
	for row in rows:
		if frappe.db.exists(
			"Compliance Activity",
			{"obligation": obligation.name, "period_label": row["period_label"]},
		):
			continue
		_insert(obligation, row, today)
		created += 1
	return created


def _payload(obligation):
	return {
		"frequency": obligation.frequency,
		"period_basis": obligation.period_basis,
		"due_day": obligation.due_day,
		"due_month_offset": obligation.due_month_offset,
		"effective_from": obligation.effective_from,
		"effective_to": obligation.effective_to,
		"schedule_overrides": [row.as_dict() for row in (obligation.schedule_overrides or [])],
	}


def _insert(obligation, row, today):
	flag, late = overdue_flags("Not Started", row["due_date"], today)
	checklist = [{"step": item.step, "is_done": 0} for item in (obligation.checklist or [])]
	doc = frappe.get_doc(
		{
			"doctype": "Compliance Activity",
			"title": f"{obligation.title} — {row['period_label']}",
			"obligation": obligation.name,
			"domain": obligation.domain,
			"risk": obligation.risk,
			"scope": obligation.scope,
			"company": obligation.company,
			"site": obligation.site if obligation.scope == "Site" else None,
			"registration": obligation.registration,
			"law_reference": obligation.law_reference,
			"period_label": row["period_label"],
			"period_start": row["period_start"],
			"period_end": row["period_end"],
			"due_date": row["due_date"],
			"status": "Not Started",
			"is_overdue": 1 if flag else 0,
			"days_late": late,
			"responsible_user": obligation.responsible_user,
			"reviewer": obligation.reviewer,
			"evidence_required": obligation.evidence_required,
			"auto_complete_from_evidence": obligation.auto_complete_from_evidence,
			"source": "Manual",
			"checklist": checklist,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def ensure_expiry_activity(obligation_name, valid_to, today=None):
	"""Create the renewal activity for a known expiry, including dates outside the usual window."""
	today = getdate(today or getdate())
	valid_to = getdate(valid_to)
	obligation = frappe.get_doc("Compliance Obligation", obligation_name)
	label = f"Renewal {valid_to.isoformat()}"
	if frappe.db.exists("Compliance Activity", {"obligation": obligation.name, "period_label": label}):
		return None
	return _insert(
		obligation,
		{
			"period_label": label,
			"period_start": valid_to,
			"period_end": valid_to,
			"due_date": valid_to,
		},
		today,
	)


def extend_due(new_date, reason, obligation=None, domain=None, period_label=None):
	if not obligation and not domain:
		frappe.throw("Choose an obligation or a domain to extend.")
	if not reason:
		frappe.throw("Record why the deadline moved.")
	new_date = getdate(new_date)
	filters = {"status": ["not in", ["Completed", "Not Applicable", "Waived"]]}
	if obligation:
		filters["obligation"] = obligation
	if domain:
		filters["domain"] = domain
	if period_label:
		filters["period_label"] = period_label
	names = frappe.get_all("Compliance Activity", filters=filters, pluck="name")
	for name in names:
		doc = frappe.get_doc("Compliance Activity", name)
		if not doc.original_due_date:
			doc.original_due_date = doc.due_date
		doc.due_date = new_date
		doc.extension_reason = reason
		doc.save(ignore_permissions=True)
	return {"updated": len(names)}

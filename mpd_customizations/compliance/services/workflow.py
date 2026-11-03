"""Apply an activity action and keep the linked Task in step."""

import frappe
from frappe.utils import now_datetime

from mpd_customizations.compliance.services.access import require_activity_write
from mpd_customizations.compliance.services.status import TERMINAL, evidence_block, overdue_flags, transition


def apply_action(name, action, ack_no=None, amount_paid=None, na_reason=None, comment=None):
	doc = frappe.get_doc("Compliance Activity", name)
	require_activity_write(doc)
	next_status, error = transition(doc.status, action, bool(doc.reviewer))
	if error:
		frappe.throw(error)
	if next_status == "Completed":
		block = evidence_block(doc.evidence_required, len(doc.evidence or []), ack_no or doc.ack_no)
		if block:
			frappe.throw(block)
	if ack_no:
		doc.ack_no = ack_no
	if amount_paid not in (None, ""):
		doc.amount_paid = amount_paid
	if action == "not_applicable":
		doc.na_reason = na_reason or doc.na_reason
		if not doc.na_reason:
			frappe.throw("Say why this activity does not apply.")
	doc.status = next_status
	if next_status == "Completed":
		doc.completed_by = doc.completed_by or frappe.session.user
		doc.completed_on = doc.completed_on or now_datetime()
	if action == "approve":
		doc.approved_by = frappe.session.user
		doc.approved_on = now_datetime()
	_refresh_overdue(doc)
	note = comment
	if frappe.flags.get("compliance_via_mcp"):
		note = comment or f"{action} via MCP by {frappe.session.user}"
	doc.save(ignore_permissions=True)
	if note:
		doc.add_comment("Comment", note)
	return doc


def _refresh_overdue(doc):
	flag, late = overdue_flags(doc.status, doc.due_date, frappe.utils.getdate())
	doc.is_overdue = 1 if flag else 0
	doc.days_late = late


def refresh_overdue_flags():
	today = frappe.utils.getdate()
	names = frappe.get_all(
		"Compliance Activity",
		filters={"status": ["not in", list(TERMINAL)]},
		pluck="name",
	)
	for name in names:
		doc = frappe.get_doc("Compliance Activity", name)
		flag, late = overdue_flags(doc.status, doc.due_date, today)
		if int(doc.is_overdue or 0) != int(flag) or int(doc.days_late or 0) != late:
			frappe.db.set_value(
				"Compliance Activity",
				name,
				{"is_overdue": 1 if flag else 0, "days_late": late},
				update_modified=False,
			)

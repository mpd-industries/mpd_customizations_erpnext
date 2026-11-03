"""Daily reminders, escalation, registration expiry, and the weekly digest."""

import frappe
from frappe.utils import escape_html, getdate, now_datetime

from mpd_customizations.compliance.services.status import (
	ESCALATION_MARKER,
	OVERDUE_MARKER,
	offsets_to_send,
	overdue_should_send,
	parse_offsets,
	should_escalate,
)
from mpd_customizations.compliance.services.workflow import refresh_overdue_flags


def daily():
	if not frappe.db.exists("DocType", "Compliance Activity"):
		return
	from mpd_customizations.compliance.services.generate import generate_all

	generate_all()
	refresh_overdue_flags()
	_expire_registrations()
	_remind()
	_maybe_digest()
	frappe.db.commit()


def _settings():
	if frappe.db.exists("Compliance Settings", "Compliance Settings"):
		return frappe.get_single("Compliance Settings")
	return frappe._dict(
		default_reminder_days="90,60,30,15,7,1,0",
		overdue_reminder_every_days=7,
		escalation_after_days=14,
		digest_weekday="Monday",
		companies=[],
	)


def _remind():
	settings = _settings()
	today = getdate()
	default_offsets = parse_offsets(settings.default_reminder_days)
	every = int(settings.overdue_reminder_every_days or 7)
	after = int(settings.escalation_after_days or 14)
	names = frappe.get_all(
		"Compliance Activity",
		filters={"status": ["not in", ["Completed", "Not Applicable", "Waived"]]},
		pluck="name",
	)
	for name in names:
		try:
			_process(name, today, default_offsets, every, after, settings)
		except Exception:
			frappe.log_error(title=f"Compliance reminder failed for {name}", message=frappe.get_traceback())


def _process(name, today, default_offsets, every, after, settings):
	doc = frappe.get_doc("Compliance Activity", name)
	due = doc.due_date
	if not due:
		return
	due = getdate(due)
	offsets = parse_offsets(_obligation_offsets(doc) or "") or default_offsets
	already = [row.days_before for row in doc.reminders if row.due_date and getdate(row.due_date) == due]
	changed = False
	for offset in offsets_to_send(due, today, offsets, already):
		_send(doc, due, offset, _parties(doc))
		changed = True
	last = _last(doc, due, OVERDUE_MARKER)
	if overdue_should_send(due, today, every, last):
		_send(doc, due, OVERDUE_MARKER, _parties(doc))
		changed = True
	if should_escalate(due, today, after, ESCALATION_MARKER in already):
		extra = _escalation_user(doc, settings)
		if extra:
			_send(doc, due, ESCALATION_MARKER, extra)
			changed = True
	if changed:
		doc.save(ignore_permissions=True)


def _obligation_offsets(doc):
	if not doc.obligation:
		return ""
	return frappe.db.get_value("Compliance Obligation", doc.obligation, "reminder_days") or ""


def _last(doc, due, marker):
	last = None
	for row in doc.reminders:
		if row.days_before != marker or not row.sent_on:
			continue
		if row.due_date and getdate(row.due_date) != due:
			continue
		sent = getdate(row.sent_on)
		if last is None or sent > last:
			last = sent
	return last


def _parties(doc):
	users = set()
	if doc.responsible_user:
		users.add(doc.responsible_user)
	if doc.reviewer:
		users.add(doc.reviewer)
	return users


def _escalation_user(doc, settings):
	for row in settings.companies or []:
		if doc.company and row.company == doc.company and row.escalation_user:
			return {row.escalation_user}
	for row in settings.companies or []:
		if row.escalation_user:
			return {row.escalation_user}
	return set()


def _send(doc, due, offset, users):
	emails = []
	for user in sorted(users or []):
		email = frappe.db.get_value("User", user, "email")
		if email:
			emails.append(email)
	if offset == ESCALATION_MARKER:
		subject = frappe._("Escalation: {0}").format(doc.title)
	elif offset == OVERDUE_MARKER:
		subject = frappe._("Overdue: {0}").format(doc.title)
	elif offset == 0:
		subject = frappe._("Due today: {0}").format(doc.title)
	else:
		subject = frappe._("{0} is due in {1} days").format(doc.title, offset)
	link = frappe.utils.get_url_to_form("Compliance Activity", doc.name)
	message = (
		f"<p>{escape_html(subject)}</p><p>Due date: {due}</p>"
		f'<p><a href="{link}">Open the activity</a></p>'
	)
	if emails:
		frappe.sendmail(recipients=emails, subject=subject, message=message, delayed=False)
	for user in sorted(users or []):
		frappe.get_doc(
			{
				"doctype": "Notification Log",
				"subject": subject,
				"email_content": message,
				"for_user": user,
				"type": "Alert",
				"document_type": "Compliance Activity",
				"document_name": doc.name,
			}
		).insert(ignore_permissions=True)
	doc.append(
		"reminders",
		{
			"due_date": due,
			"days_before": offset,
			"sent_on": now_datetime(),
			"recipients": ", ".join(emails),
			"channel": "Email, System Notification",
		},
	)


def _expire_registrations():
	today = getdate()
	names = frappe.get_all(
		"Compliance Registration",
		filters={"status": "Active", "valid_to": ["<", today]},
		pluck="name",
	)
	for name in names:
		frappe.db.set_value("Compliance Registration", name, "status", "Expired")


def _maybe_digest():
	settings = _settings()
	weekday = getdate().strftime("%A")
	if weekday != (settings.digest_weekday or "Monday"):
		return
	for row in settings.companies or []:
		_digest_company(row, settings)


def _digest_company(row, settings):
	company = row.company
	today = getdate()
	soon = frappe.utils.add_days(today, 14)
	overdue = frappe.get_all(
		"Compliance Activity",
		filters={
			"company": company,
			"is_overdue": 1,
			"status": ["not in", ["Completed", "Not Applicable", "Waived"]],
		},
		fields=["title", "due_date"],
		limit=20,
	)
	upcoming = frappe.get_all(
		"Compliance Activity",
		filters={
			"company": company,
			"status": ["not in", ["Completed", "Not Applicable", "Waived"]],
			"due_date": ["between", [today, soon]],
		},
		fields=["title", "due_date"],
		limit=20,
	)
	review = frappe.get_all(
		"Compliance Activity",
		filters={"company": company, "status": "Pending Review"},
		pluck="title",
		limit=20,
	)
	expiring = frappe.get_all(
		"Compliance Registration",
		filters={
			"company": company,
			"status": "Active",
			"valid_to": ["between", [today, frappe.utils.add_days(today, 90)]],
		},
		fields=["registration_type", "valid_to"],
		limit=20,
	)
	unowned = frappe.get_all(
		"Compliance Obligation",
		filters={"company": company, "status": "Active", "responsible_user": ["is", "not set"]},
		pluck="title",
		limit=20,
	)
	drafts = frappe.get_all(
		"Compliance Obligation",
		filters={"status": "Draft", "source": "Agent", "company": company},
		pluck="title",
		limit=20,
	)
	if not any((overdue, upcoming, review, expiring, unowned, drafts)):
		return
	parts = [f"<h3>Compliance digest — {escape_html(company)}</h3>"]
	parts.append(_list("Overdue", [f"{row.title} ({row.due_date})" for row in overdue]))
	parts.append(_list("Due in 14 days", [f"{row.title} ({row.due_date})" for row in upcoming]))
	parts.append(_list("Pending review", review))
	parts.append(
		_list("Registrations expiring", [f"{row.registration_type} ({row.valid_to})" for row in expiring])
	)
	parts.append(_list("Obligations without an owner", unowned))
	parts.append(_list("Agent drafts waiting", drafts))
	recipients = [part.strip() for part in (row.digest_recipients or "").split(",") if part.strip()]
	if not recipients and row.escalation_user:
		email = frappe.db.get_value("User", row.escalation_user, "email")
		if email:
			recipients = [email]
	if recipients:
		frappe.sendmail(
			recipients=recipients,
			subject=f"Compliance digest — {company}",
			message="".join(parts),
			delayed=False,
		)


def _list(title, rows):
	if not rows:
		return ""
	items = "".join(f"<li>{escape_html(str(row))}</li>" for row in rows)
	return f"<p><strong>{escape_html(title)}</strong></p><ul>{items}</ul>"

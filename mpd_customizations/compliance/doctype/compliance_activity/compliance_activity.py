import frappe
from frappe.model.document import Document

from mpd_customizations.compliance.services.access import is_manager
from mpd_customizations.compliance.services.scope import scope_error
from mpd_customizations.compliance.services.tasks import sync_task
from mpd_customizations.compliance.services.workflow import _refresh_overdue


class ComplianceActivity(Document):
	def validate(self):
		if self.scope != "Site":
			self.site = None
		error = scope_error(self.scope, self.company, self.site)
		if error:
			frappe.throw(error)
		before = self.get_doc_before_save()
		if before and before.status == "Completed" and not is_manager():
			if len(self.evidence or []) != len(before.evidence or []):
				frappe.throw("Evidence is locked after completion. Ask a Compliance Manager to change it.")
		_refresh_overdue(self)
		if frappe.flags.get("compliance_via_mcp") and self.is_new() and self.source == "Manual":
			self.source = "Agent"

	def on_update(self):
		sync_task(self)
		_sync_event(self)


def _sync_event(doc):
	if not frappe.db.exists("Compliance Settings", "Compliance Settings"):
		return
	if not frappe.db.get_single_value("Compliance Settings", "create_calendar_events"):
		return
	if not doc.due_date or doc.status in ("Completed", "Not Applicable", "Waived"):
		if doc.calendar_event and frappe.db.exists("Event", doc.calendar_event):
			frappe.db.set_value("Event", doc.calendar_event, "status", "Cancelled")
		return
	if doc.calendar_event and frappe.db.exists("Event", doc.calendar_event):
		frappe.db.set_value(
			"Event",
			doc.calendar_event,
			{"subject": doc.title, "starts_on": doc.due_date, "ends_on": doc.due_date, "status": "Open"},
		)
		return
	event = frappe.get_doc(
		{
			"doctype": "Event",
			"subject": doc.title,
			"starts_on": doc.due_date,
			"ends_on": doc.due_date,
			"all_day": 1,
			"event_type": "Public",
		}
	)
	event.insert(ignore_permissions=True)
	frappe.db.set_value("Compliance Activity", doc.name, "calendar_event", event.name, update_modified=False)

"""Mirror each activity to a Task on the company's compliance project."""

import frappe
from frappe.utils import getdate

CLOSED = {"Completed", "Not Applicable", "Waived"}
TASK_CLOSED = {"Completed", "Cancelled"}


def project_for(company):
	if not frappe.db.exists("DocType", "Compliance Settings"):
		return None
	settings = frappe.get_single("Compliance Settings")
	rows = list(settings.companies or [])
	if company:
		for row in rows:
			if row.company == company and row.project:
				return row.project
	for row in rows:
		if row.project:
			return row.project
	return None


def sync_task(activity):
	if frappe.flags.get("in_compliance_task_sync"):
		return
	if isinstance(activity, str):
		activity = frappe.get_doc("Compliance Activity", activity)
	project = activity.project or project_for(activity.company)
	if not project:
		return
	frappe.flags.in_compliance_task_sync = True
	try:
		task = _upsert(activity, project)
		if activity.project != project or activity.task != task.name:
			frappe.db.set_value(
				"Compliance Activity",
				activity.name,
				{"project": project, "task": task.name},
				update_modified=False,
			)
			activity.project = project
			activity.task = task.name
	finally:
		frappe.flags.in_compliance_task_sync = False


def _upsert(activity, project):
	description = _description(activity)
	status = "Completed" if activity.status in CLOSED else "Open"
	if activity.task and frappe.db.exists("Task", activity.task):
		task = frappe.get_doc("Task", activity.task)
	else:
		task = frappe.new_doc("Task")
		task.status = "Open"
	task.subject = (activity.title or "Compliance activity")[:140]
	task.project = project
	task.description = description
	if activity.due_date:
		task.exp_end_date = getdate(activity.due_date)
	task.status = status
	task.flags.ignore_permissions = True
	if task.is_new():
		task.insert(ignore_permissions=True)
	else:
		task.save(ignore_permissions=True)
	_assign(task.name, activity.responsible_user)
	return task


def _description(activity):
	lines = [activity.law_reference or "", activity.period_label or ""]
	for row in activity.checklist or []:
		mark = "x" if row.is_done else " "
		lines.append(f"- [{mark}] {row.step}")
	lines.append(f"/desk/compliance-activity/{activity.name}")
	return "\n".join(line for line in lines if line)


def _assign(task_name, user):
	if not user:
		return
	from frappe.desk.form.assign_to import add as assign

	try:
		assign({"assign_to": [user], "doctype": "Task", "name": task_name, "notify": 0})
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"Could not assign {task_name}")


def on_task_update(doc, method=None):
	if frappe.flags.get("in_compliance_task_sync"):
		return
	activity_name = frappe.db.get_value("Compliance Activity", {"task": doc.name}, "name")
	if not activity_name:
		return
	if doc.status not in TASK_CLOSED:
		return
	activity = frappe.get_doc("Compliance Activity", activity_name)
	if activity.status in CLOSED:
		return
	from mpd_customizations.compliance.services.status import evidence_block

	if doc.status == "Cancelled":
		activity.status = "Waived"
		activity.na_reason = activity.na_reason or "Task cancelled"
	else:
		block = evidence_block(activity.evidence_required, len(activity.evidence or []), activity.ack_no)
		if block:
			frappe.throw(block)
		if activity.reviewer and activity.status != "Pending Review":
			activity.status = "Pending Review"
		else:
			activity.status = "Completed"
			activity.completed_by = activity.completed_by or frappe.session.user
			activity.completed_on = activity.completed_on or frappe.utils.now_datetime()
	frappe.flags.in_compliance_task_sync = True
	try:
		activity.save(ignore_permissions=True)
	finally:
		frappe.flags.in_compliance_task_sync = False

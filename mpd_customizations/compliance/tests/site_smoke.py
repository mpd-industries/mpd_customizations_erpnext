"""Site smoke: obligation, activity, task, evidence gate, and an agent draft. Cleans up after itself."""

import frappe


def run():
	frappe.set_user("Administrator")
	company = "MPD Industries Pvt Ltd"
	created = {"obligations": [], "activities": [], "tasks": [], "events": []}
	try:
		_assert_scope_rules(company)
		_agent_draft_and_task(company, created)
		return {"ok": True, "checked": created["activities"]}
	finally:
		_cleanup(created)
		frappe.db.commit()


def _assert_scope_rules(company):
	from mpd_customizations.compliance.services.scope import scope_error

	if not scope_error("Site", company, None):
		frappe.throw("A site obligation without a site was accepted.")
	if scope_error("Group", None, None):
		frappe.throw("A group obligation was rejected.")


def _agent_draft_and_task(company, created):
	from mpd_customizations.compliance.api import actions

	frappe.flags.compliance_via_mcp = True
	try:
		draft = actions.add_obligation(
			title="SMOKE GSTR-3B",
			domain="GST & Indirect Tax",
			scope="Company",
			company=company,
			frequency="Monthly",
			due_day=20,
			due_month_offset=1,
			period_basis="Calendar",
			effective_from="2026-10-01",
			evidence_required=1,
		)
	finally:
		frappe.flags.compliance_via_mcp = False
	created["obligations"].append(draft["name"])
	if draft["status"] != "Draft":
		frappe.throw(f"Agent obligation was {draft['status']}, expected Draft.")
	source = frappe.db.get_value("Compliance Obligation", draft["name"], "source")
	if source != "Agent":
		frappe.throw(f"Agent obligation source was {source}.")

	actions.set_obligation_status(draft["name"], "Active")
	rows = frappe.get_all(
		"Compliance Activity",
		filters={"obligation": draft["name"]},
		fields=["name", "task", "calendar_event", "status", "due_date"],
	)
	if not rows:
		frappe.throw("Activating the obligation did not create an activity.")
	for activity in rows:
		created["activities"].append(activity.name)
		if activity.calendar_event:
			created["events"].append(activity.calendar_event)
		if activity.task:
			created["tasks"].append(activity.task)
	activity = rows[0]
	if not activity.task or not frappe.db.exists("Task", activity.task):
		frappe.throw("The activity has no Task.")

	task = frappe.get_doc("Task", activity.task)
	task.status = "Completed"
	frappe.db.savepoint("smoke_gate")
	blocked = False
	try:
		task.save(ignore_permissions=True)
	except frappe.ValidationError as exc:
		blocked = "evidence" in str(exc).lower() or "acknowledgement" in str(exc).lower()
		frappe.db.rollback(save_point="smoke_gate")
	if not blocked:
		frappe.throw("Closing the Task without evidence was allowed.")

	frappe.db.set_value("Compliance Activity", activity.name, "ack_no", "SMOKE-ACK")
	task = frappe.get_doc("Task", activity.task)
	task.status = "Completed"
	task.save(ignore_permissions=True)
	status = frappe.db.get_value("Compliance Activity", activity.name, "status")
	if status != "Completed":
		frappe.throw(f"Closing the Task left the activity {status}.")


def _cleanup(created):
	for name in created["activities"]:
		if frappe.db.exists("Compliance Activity", name):
			frappe.delete_doc("Compliance Activity", name, force=1, ignore_permissions=True)
	for name in created["tasks"]:
		if frappe.db.exists("Task", name):
			frappe.delete_doc("Task", name, force=1, ignore_permissions=True)
	for name in created["events"]:
		if frappe.db.exists("Event", name):
			frappe.delete_doc("Event", name, force=1, ignore_permissions=True)
	for name in created["obligations"]:
		if frappe.db.exists("Compliance Obligation", name):
			frappe.delete_doc("Compliance Obligation", name, force=1, ignore_permissions=True)

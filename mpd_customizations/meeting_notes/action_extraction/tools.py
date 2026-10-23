import json as _json
import re

import frappe
from frappe import _


def get_backlog(project, status_filter=None):
	if status_filter is None:
		status_filter = ["Open", "Working", "Pending Review"]

	_fields = ["name", "subject", "status", "_assign", "priority", "md_description", "exp_end_date"]

	open_tasks = frappe.get_all(
		"Task",
		filters={"project": project, "status": ["in", status_filter]},
		fields=_fields,
		limit=300,
		order_by="exp_end_date asc",
	)
	for t in open_tasks:
		raw = t.pop("_assign", None)
		t["assigned_to"] = (_json.loads(raw)[0] if raw else None)

	recent_closed = frappe.get_all(
		"Task",
		filters={"project": project, "status": ["in", ["Completed", "Cancelled"]]},
		fields=_fields,
		limit=10,
		order_by="modified desc",
	)
	for t in recent_closed:
		raw = t.pop("_assign", None)
		t["assigned_to"] = (_json.loads(raw)[0] if raw else None)

	return {
		"project": project,
		"open_count": len(open_tasks),
		"tasks": open_tasks,
		"recently_closed": recent_closed,
	}


def update_existing_task(task_name, comment,
	new_priority=None,
	objective=None,
	acceptance_criteria=None,
	new_due_date=None,
	new_assignee=None,
	new_status=None):

	task = frappe.get_doc("Task", task_name)
	changed = False

	if objective or acceptance_criteria:
		task.md_description = _patch_description(
			task.md_description or "",
			objective=objective,
			acceptance_criteria=acceptance_criteria,
		)
		changed = True

	if new_priority:
		task.priority = new_priority
		changed = True

	if new_due_date:
		task.exp_end_date = new_due_date
		changed = True

	if new_status:
		task.status = new_status
		if new_status == "Completed":
			task.completed_on = frappe.utils.nowdate()
		changed = True

	if changed:
		task.save(ignore_permissions=True)

	if new_assignee:
		frappe.db.commit()  # must commit before assign_to can find the task
		try:
			from frappe.desk.form.assign_to import add as _assign_add
			_assign_add({
				"assign_to": [new_assignee],
				"doctype": "Task",
				"name": task_name,
				"notify": 0,
			})
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"Could not assign {new_assignee} to {task_name}")

	comment_doc = frappe.new_doc("Comment")
	comment_doc.comment_type = "Comment"
	comment_doc.reference_doctype = "Task"
	comment_doc.reference_name = task_name
	comment_doc.content = f"[Meeting Update] {comment}"
	comment_doc.insert(ignore_permissions=True)

	frappe.db.commit()
	return {"task": task_name, "status": "updated", "comment_added": True}


def reopen_task(task_name, comment, new_due_date=None):
	task = frappe.get_doc("Task", task_name)
	task.status = "Open"
	if new_due_date:
		task.exp_end_date = new_due_date
	task.save(ignore_permissions=True)

	comment_doc = frappe.new_doc("Comment")
	comment_doc.comment_type = "Comment"
	comment_doc.reference_doctype = "Task"
	comment_doc.reference_name = task_name
	comment_doc.content = f"[Meeting Update — Reopened] {comment}"
	comment_doc.insert(ignore_permissions=True)

	frappe.db.commit()
	return {"task": task_name, "status": "reopened"}


def create_pending_task(subject, project, description,
	suggested_assignee=None, priority="Medium", exp_end_date=None,
	objective=None, acceptance_criteria=None):

	full_description = _patch_description(description or "", objective=objective, acceptance_criteria=acceptance_criteria)

	task = frappe.new_doc("Task")
	task.subject = subject
	task.project = project
	task.md_description = full_description
	task.priority = priority
	task.status = "Open"
	task.suggested_assignee = suggested_assignee or ""
	task.exp_end_date = exp_end_date or _default_due_date()

	task.insert(ignore_permissions=True)
	frappe.db.commit()  # must commit before assign_to can find the task

	if suggested_assignee:
		try:
			from frappe.desk.form.assign_to import add as _assign_add
			_assign_add({"assign_to": [suggested_assignee], "doctype": "Task", "name": task.name, "notify": 0})
			frappe.db.commit()
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"Could not assign {suggested_assignee} to {task.name}")

	return {"name": task.name, "subject": task.subject}


def create_subtask(subject, parent_task, project,
	description=None, suggested_assignee=None,
	priority="Medium", exp_end_date=None):

	task = frappe.new_doc("Task")
	task.subject = subject
	task.parent_task = parent_task
	task.project = project
	task.md_description = description or ""
	task.suggested_assignee = suggested_assignee or ""
	task.priority = priority
	task.status = "Open"
	if exp_end_date:
		task.exp_end_date = exp_end_date
	task.insert(ignore_permissions=True)
	frappe.db.commit()
	return {"name": task.name, "subject": task.subject, "parent_task": parent_task}


# ─── helpers ──────────────────────────────────────────────────────────────────

def _default_due_date():
	"""Returns a date string 4 working days (Mon–Fri) from today."""
	from frappe.utils import add_days, getdate
	d = getdate()
	added = 0
	while added < 4:
		d = add_days(d, 1)
		if d.weekday() < 5:  # 0=Mon … 4=Fri
			added += 1
	return str(d)

def _patch_description(current: str, objective=None, acceptance_criteria=None) -> str:
	"""Insert or replace ## Objective / ## Acceptance Criteria sections in description."""

	def _replace_section(text, header, content):
		pattern = rf"(## {re.escape(header)}\n)(.*?)(?=\n## |\Z)"
		replacement = f"## {header}\n{content}\n\n"
		if re.search(pattern, text, re.DOTALL):
			return re.sub(pattern, replacement, text, flags=re.DOTALL)
		return text.rstrip() + f"\n\n## {header}\n{content}"

	if objective:
		current = _replace_section(current, "Objective", objective.strip())
	if acceptance_criteria:
		current = _replace_section(current, "Acceptance Criteria", acceptance_criteria.strip())

	return current.strip()

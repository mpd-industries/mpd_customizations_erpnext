import os

import frappe
from frappe import _
from frappe.model.document import Document


class MeetingNote(Document):

    @frappe.whitelist()
    def get_project_tasks(self):
        if not self.project:
            return []
        tasks = frappe.get_all(
            "Task",
            filters={"project": self.project, "status": ["in", ["Open", "Working", "Pending Review"]]},
            fields=["name", "subject", "_assign", "exp_end_date", "status", "priority"],
            order_by="exp_end_date asc",
            limit=200,
        )
        import json as _json
        for t in tasks:
            raw = t.pop("_assign", None)
            assignees = _json.loads(raw) if raw else []
            t["assigned_to"] = assignees[0] if assignees else None
        return tasks

    @frappe.whitelist()
    def start_transcription(self):
        if not self.audio_file:
            frappe.throw(_("No audio file to transcribe."))
        if self.status != "Draft":
            frappe.throw(_("Transcription can only be started from Draft status. Current status: {0}").format(self.status))

        self.status = "Transcribing"
        self.save(ignore_permissions=True)
        frappe.db.commit()

        frappe.enqueue(
            "mpd_customizations.action_extraction.pipeline.run_transcription",
            meeting_note_name=self.name,
            queue="long",
            timeout=900,
        )

    @frappe.whitelist()
    def start_extraction(self):
        if not self.transcript:
            frappe.throw(_("Transcribe the audio first, or paste a transcript manually."))
        if self.status != "Draft":
            frappe.throw(_("Extraction can only be started from Draft status. Current status: {0}").format(self.status))

        self.status = "Processing"
        self.save(ignore_permissions=True)
        frappe.db.commit()

        frappe.enqueue(
            "mpd_customizations.action_extraction.pipeline.run",
            meeting_note_name=self.name,
            queue="long",
            timeout=900,
        )

    @frappe.whitelist()
    def get_pending_tasks(self):
        tasks = frappe.get_all(
            "Task",
            filters={
                "project": self.project,
                "creation": [">=", self.meeting_date],
            },
            fields=[
                "name", "subject", "description", "priority",
                "suggested_assignee", "exp_end_date",
                "status", "parent_task",
            ],
        )
        return tasks

    def _approve_task(self, task_name, assignee=None):
        task = frappe.get_doc("Task", task_name)
        task.status = "Open"
        effective_assignee = assignee or task.suggested_assignee
        task.save(ignore_permissions=True)
        frappe.db.commit()
        if effective_assignee:
            from frappe.desk.form.assign_to import add as assign_to_add
            try:
                assign_to_add({
                    "assign_to": [effective_assignee],
                    "doctype": "Task",
                    "name": task_name,
                    "notify": 0,
                })
                frappe.db.commit()
            except Exception:
                frappe.log_error(frappe.get_traceback(), f"Could not assign {effective_assignee} to {task_name}")
        return {"status": "approved", "task": task_name}

    def _reject_task(self, task_name):
        task = frappe.get_doc("Task", task_name)
        task.status = "Cancelled"
        task.save(ignore_permissions=True)
        frappe.db.commit()
        return {"status": "rejected", "task": task_name}

    @frappe.whitelist()
    def bulk_approve(self, approvals):
        import json
        if isinstance(approvals, str):
            approvals = json.loads(approvals)

        approved = 0
        rejected = 0
        errors = []

        for item in approvals:
            try:
                if item.get("action") == "reject":
                    self._reject_task(item["task_name"])
                    rejected += 1
                else:
                    self._approve_task(item["task_name"], assignee=item.get("assignee"))
                    approved += 1
            except Exception as e:
                frappe.log_error(frappe.get_traceback(), f"bulk_approve failed on {item.get('task_name')}")
                errors.append({"task": item.get("task_name"), "error": str(e)})

        if errors:
            return {"approved": approved, "rejected": rejected, "errors": errors}

        self.reload()
        self.status = "Completed"
        self.save(ignore_permissions=True)
        frappe.db.commit()
        return {"approved": approved, "rejected": rejected, "errors": []}

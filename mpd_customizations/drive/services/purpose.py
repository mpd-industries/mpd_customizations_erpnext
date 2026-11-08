"""Refresh a folder meaning from the files that are in it now."""

import frappe

from mpd_customizations.drive.ai.purpose import accept_model_purpose, learned_purpose, purpose_request_text


def refresh_folder_meanings(names):
	"""Rewrite learned meanings for these folders and their parents.

	A meaning saved by a person is left as they wrote it. AI Input folders are skipped.
	"""
	if not names or not frappe.db.has_column("Drive Folder", "purpose"):
		return []
	leaves = []
	parents = []
	for name in names:
		if name and name not in leaves:
			leaves.append(name)
		parent = frappe.db.get_value("Drive Folder", name, "parent_drive_folder") if name else None
		if parent and parent not in parents:
			parents.append(parent)
	ordered = [name for name in leaves if name not in parents]
	ordered.extend(parents)
	return [name for name in ordered if _refresh_one(name)]


def _refresh_one(name):
	fields = ["purpose", "purpose_custom", "is_trashed", "is_ai_inbox"]
	if not frappe.db.has_column("Drive Folder", "purpose_custom"):
		fields = ["purpose", "is_trashed", "is_ai_inbox"]
	fields = ["title", *fields]
	row = frappe.db.get_value("Drive Folder", name, fields, as_dict=True)
	if not row or row.is_trashed or row.is_ai_inbox:
		return False
	custom = bool(row.get("purpose_custom")) and (row.purpose or "").strip()
	if custom:
		return False
	files = frappe.get_all(
		"Drive File",
		filters={"folder": name, "is_trashed": 0, "status": "Uploaded"},
		fields=["title", "ai_document_type", "ai_summary"],
		order_by="modified desc",
		limit=12,
	)
	child_fields = ["title", "purpose"] if frappe.db.has_column("Drive Folder", "purpose") else ["title"]
	children = frappe.get_all(
		"Drive Folder",
		filters={"parent_drive_folder": name, "is_trashed": 0, "is_ai_inbox": 0},
		fields=child_fields,
		order_by="title asc",
		limit=8,
	)
	file_rows = [
		{"title": item.title, "document_type": item.ai_document_type, "summary": item.ai_summary}
		for item in files
	]
	child_rows = [{"title": item.title, "purpose": item.get("purpose")} for item in children]
	text = _model_purpose(name, row.title, file_rows, child_rows, row.purpose or "")
	if not text:
		text = learned_purpose(file_rows, children=child_rows, existing=row.purpose or "", keep=False)
	if text == (row.purpose or "").strip():
		return False
	frappe.db.set_value("Drive Folder", name, "purpose", text)
	return True


def _model_purpose(name, title, files, children, existing):
	"""Ask the filing model for the folder meaning. An empty string means try the fallback."""
	if not files and not children:
		return ""
	try:
		from mpd_customizations.mpd_base.ai.llm import call_llm
		from mpd_customizations.mpd_base.ai.task_config import get_task_config

		config, _params = get_task_config("drive_folder_purpose")
		result = call_llm(
			config,
			config.system_prompt,
			purpose_request_text(title, files, children, existing),
			reference_doctype="Drive Folder",
			reference_name=name,
		)
	except Exception:
		frappe.log_error(title=f"Drive folder meaning failed for {name}", message=frappe.get_traceback())
		return ""
	return accept_model_purpose(result)

"""Seed Drive settings, roles, default folders, and inbox routes."""

import frappe

from mpd_customizations.drive.ai.filing import APR_HANDLER

DEFAULT_ROUTES = ("Invoice", "PO", "Quote")


def after_install():
	after_migrate()


def after_migrate():
	if not frappe.db.exists("DocType", "Drive Settings"):
		return
	_ensure_roles()
	_ensure_settings()
	_ensure_routes()
	_ensure_folders()
	_sync_classify_prompt()
	frappe.db.commit()


def _sync_classify_prompt():
	if not frappe.db.exists("DocType", "AI Task Config"):
		return
	from mpd_customizations.drive.ai.prompts import INBOX_CLASSIFY_PROMPT

	name = frappe.db.get_value("AI Task Config", {"task_key": "drive_inbox_classify"}, "name")
	if not name:
		return
	doc = frappe.get_doc("AI Task Config", name)
	if doc.system_prompt == INBOX_CLASSIFY_PROMPT:
		return
	doc.system_prompt = INBOX_CLASSIFY_PROMPT
	doc.save(ignore_permissions=True)


def _ensure_roles():
	for role_name in ("Drive Admin",):
		if frappe.db.exists("Role", role_name):
			continue
		frappe.get_doc({"doctype": "Role", "role_name": role_name, "desk_access": 1, "is_custom": 1}).insert(
			ignore_permissions=True
		)


def _ensure_settings():
	if frappe.db.exists("Drive Settings", "Drive Settings"):
		return
	frappe.get_doc({"doctype": "Drive Settings"}).insert(ignore_permissions=True)


def _ensure_routes():
	doc = frappe.get_single("Drive Settings")
	existing = {row.document_type for row in doc.inbox_routes}
	changed = False
	for document_type in DEFAULT_ROUTES:
		if document_type in existing:
			continue
		doc.append(
			"inbox_routes",
			{"document_type": document_type, "handler": APR_HANDLER, "enabled": 1},
		)
		changed = True
	if changed:
		doc.save(ignore_permissions=True)


def _ensure_folders():
	documents = _ensure_folder("Documents")
	_ensure_ai_input(documents, "General", documents)
	_grant(documents, "All", "Edit")


def _ensure_ai_input(parent, inbox_kind, organise_into):
	existing = frappe.db.get_value(
		"Drive Folder",
		{"parent_drive_folder": parent, "is_ai_inbox": 1, "is_trashed": 0},
		"name",
	)
	if existing:
		doc = frappe.get_doc("Drive Folder", existing)
		doc.title = "AI Input"
		doc.inbox_kind = inbox_kind
		doc.organise_into = organise_into
		doc.save(ignore_permissions=True)
		return existing
	return _ensure_folder(
		"AI Input",
		parent=parent,
		is_ai_inbox=1,
		inbox_kind=inbox_kind,
		organise_into=organise_into,
	)


def _ensure_folder(title, parent=None, **extra):
	filters = {"title": title, "is_trashed": 0}
	if parent:
		filters["parent_drive_folder"] = parent
	else:
		filters["parent_drive_folder"] = ["is", "not set"]
	existing = frappe.db.get_value("Drive Folder", filters, "name")
	if existing:
		if extra:
			doc = frappe.get_doc("Drive Folder", existing)
			for key, value in extra.items():
				doc.set(key, value)
			doc.save(ignore_permissions=True)
		return existing
	doc = frappe.get_doc(
		{
			"doctype": "Drive Folder",
			"title": title,
			"parent_drive_folder": parent,
			"is_ai_inbox": extra.get("is_ai_inbox", 0),
			"inbox_kind": extra.get("inbox_kind") or "General",
			"organise_into": extra.get("organise_into"),
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def _grant(folder, role, level):
	doc = frappe.get_doc("Drive Folder", folder)
	for row in doc.permissions:
		if row.principal_type == "Role" and row.role == role:
			return
	doc.append("permissions", {"principal_type": "Role", "role": role, "level": level})
	doc.save(ignore_permissions=True)

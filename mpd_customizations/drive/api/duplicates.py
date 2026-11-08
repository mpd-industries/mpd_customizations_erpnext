"""Review files that share a content hash."""

import frappe

from mpd_customizations.drive.services.access import folders_visible_to, is_drive_admin, require_folder
from mpd_customizations.drive.services.duplicates import duplicate_groups
from mpd_customizations.drive.services.files import trash_file
from mpd_customizations.drive.services.hashing import file_location, queue_hash_backfill, watched_ids

AI_COPY_FIELDS = (
	"ai_summary",
	"ai_document_type",
	"ai_subject",
	"ai_document_date",
	"ai_tags",
	"ai_context",
	"ai_confidence",
	"ai_suggested_path",
	"ai_status",
)


def _rows():
	visible = set(folders_visible_to() or [])
	watched = watched_ids()
	names = list(visible & watched)
	if not names:
		return []
	return frappe.get_all(
		"Drive File",
		filters={
			"is_trashed": 0,
			"status": "Uploaded",
			"folder": ["in", names],
			"content_hash": ["not in", ["", "unavailable"]],
		},
		fields=[
			"name",
			"title",
			"folder",
			"content_hash",
			"duplicate_ok",
			"size",
			"owner",
			"creation",
			"ai_status",
			"ai_summary",
			"original_filename",
		],
	)


def _present(groups):
	presented = []
	for group in groups:
		files = []
		for row in group["files"]:
			folder = row.folder if hasattr(row, "folder") else row["folder"]
			title = row.title if hasattr(row, "title") else row["title"]
			original = row.original_filename if hasattr(row, "original_filename") else row.get("original_filename")
			files.append(
				{
					"name": row.name if hasattr(row, "name") else row["name"],
					"title": title,
					"original_filename": original,
					"folder": folder,
					"path": file_location(folder, title),
					"owner": row.owner if hasattr(row, "owner") else row.get("owner"),
					"creation": row.creation if hasattr(row, "creation") else row.get("creation"),
					"ai_status": row.ai_status if hasattr(row, "ai_status") else row.get("ai_status"),
					"size": row.size if hasattr(row, "size") else row.get("size"),
					"duplicate_ok": row.duplicate_ok if hasattr(row, "duplicate_ok") else row.get("duplicate_ok"),
				}
			)
		presented.append(
			{
				"content_hash": group["content_hash"],
				"wasted_bytes": group["wasted_bytes"],
				"files": files,
			}
		)
	return presented


@frappe.whitelist()
def list_duplicates():
	groups = _present(duplicate_groups(_rows()))
	return {
		"groups": groups,
		"count": len(groups),
		"match": "content hash",
	}


@frappe.whitelist()
def set_duplicate_check(folder, enabled=0):
	"""Turn content-hash duplicate check on or off for this folder and its contents."""
	require_folder(folder, "Edit")
	if not frappe.db.has_column("Drive Folder", "check_duplicates"):
		frappe.throw("Duplicate check is not available until the site is migrated.")
	value = 1 if frappe.utils.cint(enabled) else 0
	frappe.db.set_value("Drive Folder", folder, "check_duplicates", value)
	return {"name": folder, "check_duplicates": value}


def _group_files(content_hash):
	rows = [
		row
		for row in _rows()
		if (row.content_hash if hasattr(row, "content_hash") else row["content_hash"]) == content_hash
	]
	groups = duplicate_groups(rows)
	if not groups:
		frappe.throw(frappe._("These files are no longer duplicates"))
	return groups[0]["files"]


@frappe.whitelist()
def keep_one(content_hash, file_id):
	"""Trash the other copies. A missing overview is copied from a copy that has one."""
	files = _group_files(content_hash)
	names = [row.name if hasattr(row, "name") else row["name"] for row in files]
	if file_id not in names:
		frappe.throw(frappe._("That file is not in this duplicate group"))
	for name in names:
		folder = frappe.db.get_value("Drive File", name, "folder")
		require_folder(folder, "Edit")
	keeper_summary = frappe.db.get_value("Drive File", file_id, "ai_summary")
	if not (keeper_summary or "").strip():
		for name in names:
			if name == file_id:
				continue
			summary = frappe.db.get_value("Drive File", name, "ai_summary")
			if (summary or "").strip():
				values = {field: frappe.db.get_value("Drive File", name, field) for field in AI_COPY_FIELDS}
				frappe.db.set_value("Drive File", file_id, values)
				break
	trashed = []
	for name in names:
		if name == file_id:
			continue
		trash_file(name)
		trashed.append(name)
	return {"kept": file_id, "trashed": trashed}


@frappe.whitelist()
def keep_all(content_hash):
	files = _group_files(content_hash)
	for row in files:
		name = row.name if hasattr(row, "name") else row["name"]
		folder = row.folder if hasattr(row, "folder") else row["folder"]
		require_folder(folder, "Edit")
		frappe.db.set_value("Drive File", name, "duplicate_ok", 1)
	return {"content_hash": content_hash, "kept": len(files)}


@frappe.whitelist()
def rescan():
	if not is_drive_admin():
		frappe.throw(frappe._("Only a Drive Admin can rescan"), frappe.PermissionError)
	queue_hash_backfill(reset_failures=True)
	return {"queued": True}

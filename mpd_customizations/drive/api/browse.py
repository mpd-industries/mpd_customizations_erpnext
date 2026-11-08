"""Whitelisted browsing and file operations."""

import frappe

from mpd_customizations.drive.services.access import (
	folders_visible_to,
	is_drive_admin,
	level_for,
	require_folder,
	root_folders,
)
from mpd_customizations.drive.services.files import (
	delete_file_record,
	delete_folder_record,
	list_files,
	move_file,
	needs_review,
	recent_files,
	rename_file,
	restore_file,
	search_files,
	trash_file,
)
from mpd_customizations.drive.services.folders import (
	_existing_fields,
	breadcrumbs,
	child_folders,
	create_folder,
	folder_summary,
	get_or_create_child,
	mark_trashed,
	move_folder,
	rename_folder,
)
from mpd_customizations.drive.services.upload_tree import collect_upload_tree
from mpd_customizations.drive.services.permissions import level_at_least
from mpd_customizations.drive.services.sections import group_library


@frappe.whitelist()
def list_folder(folder=None):
	user = frappe.session.user
	if folder:
		level = require_folder(folder, "View", user=user)
		folders = child_folders(folder)
		for row in folders:
			row["level"] = level_for(row.name, user=user)
			row["kind"] = "folder"
		files = list_files(folder, status="Uploaded")
		for row in files:
			row["level"] = level
			row["kind"] = "file"
		return {
			"folder": folder_summary(folder, user=user),
			"breadcrumbs": breadcrumbs(folder),
			"folders": folders,
			"files": files,
			"level": level,
		}

	names = root_folders(user)
	folders = []
	for name in names:
		summary = folder_summary(name, user=user)
		if summary:
			summary["kind"] = "folder"
			folders.append(summary)
	folders.sort(key=lambda row: (row.get("title") or "").lower())
	return {"folder": None, "breadcrumbs": [], "folders": folders, "files": [], "level": None}


@frappe.whitelist()
def library_sections():
	"""Folders for the Drive, AI, and Statutory compliance sidebars."""
	visible = folders_visible_to()
	if not visible:
		return {"drive": [], "ai": [], "compliance": [], "membership": {}}
	rows = frappe.get_all(
		"Drive Folder",
		filters={"is_trashed": 0, "name": ["in", list(visible)]},
		fields=["name", "title", "parent_drive_folder", "is_ai_inbox", "inbox_kind", "organise_into"],
	)
	return group_library(rows)


@frappe.whitelist()
def get_recent():
	names = folders_visible_to()
	rows = recent_files(names)
	for row in rows:
		row["level"] = level_for(row.folder)
		row["kind"] = "file"
	return {"files": rows}


@frappe.whitelist()
def search(query=None, document_type=None, subject=None, date_from=None, date_to=None, filename=None):
	"""Search files the user can see. `filename` matches the original name and title only."""
	from mpd_customizations.drive.services.search import like_pattern

	visible = folders_visible_to()
	rows = search_files(
		visible,
		query or "",
		document_type=document_type,
		subject=subject,
		date_from=date_from,
		date_to=date_to,
		filename=filename,
	)
	for row in rows:
		row["level"] = level_for(row.folder)
		row["kind"] = "file"
	term = filename or query
	folders = []
	if term and visible:
		folders = frappe.get_all(
			"Drive Folder",
			filters={
				"is_trashed": 0,
				"name": ["in", list(visible)],
				"title": ["like", like_pattern(term)],
			},
			fields=_existing_fields(
				[
					"name",
					"title",
					"modified",
					"is_ai_inbox",
					"parent_drive_folder",
					"check_duplicates",
					"purpose",
				]
			),
			order_by="title asc",
			limit=50,
		)
		for row in folders:
			row["kind"] = "folder"
			row["level"] = level_for(row.name)
	return {"files": rows, "folders": folders}


@frappe.whitelist()
def list_review():
	rows = needs_review(folders_visible_to())
	for row in rows:
		row["level"] = level_for(row.folder)
		row["kind"] = "file"
	return {"files": rows}


@frappe.whitelist()
def list_trash():
	names = folders_visible_to(min_level="Manage")
	if not names:
		return {"folders": [], "files": []}
	folders = frappe.get_all(
		"Drive Folder",
		filters={"is_trashed": 1, "name": ["in", names]},
		fields=["name", "title", "modified", "trashed_on", "parent_drive_folder"],
	)
	files = frappe.get_all(
		"Drive File",
		filters={"is_trashed": 1, "folder": ["in", names]},
		fields=["name", "title", "folder", "size", "modified", "trashed_on", "mime_type"],
	)
	for row in folders:
		row["kind"] = "folder"
		row["level"] = "Manage"
	for row in files:
		row["kind"] = "file"
		row["level"] = "Manage"
	return {"folders": folders, "files": files}


@frappe.whitelist()
def ensure_folder_tree(parent, paths):
	"""Create each directory in `paths`, reusing a child that already has that name."""
	require_folder(parent, "Edit")
	if isinstance(paths, str):
		paths = frappe.parse_json(paths)
	tree = collect_upload_tree(paths)
	mapping = {}
	for folder_path in tree["folders"]:
		current = parent
		built = []
		for segment in folder_path.split("/"):
			built.append(segment)
			key = "/".join(built)
			if key not in mapping:
				mapping[key] = get_or_create_child(current, segment)
			current = mapping[key]
	return {"folders": mapping, "files": tree["files"]}


@frappe.whitelist()
def create_folder_item(title, parent=None):
	if parent:
		require_folder(parent, "Edit")
	elif not is_drive_admin():
		frappe.throw(frappe._("Only a Drive Admin can create a top-level folder"), frappe.PermissionError)
	doc = create_folder(title, parent=parent or None)
	return folder_summary(doc.name)


@frappe.whitelist()
def set_folder_purpose(folder, purpose=""):
	"""Save a folder meaning. A saved wording is kept when a reorganization rewrites the others."""
	require_folder(folder, "Edit")
	if not frappe.db.has_column("Drive Folder", "purpose"):
		frappe.throw("Folder meanings are not available until the site is migrated.")
	text = " ".join((purpose or "").split())[:1000]
	values = {"purpose": text}
	if frappe.db.has_column("Drive Folder", "purpose_custom"):
		values["purpose_custom"] = 1 if text else 0
	frappe.db.set_value("Drive Folder", folder, values)
	return {"name": folder, "purpose": text, "purpose_custom": 1 if text else 0}


@frappe.whitelist()
def ensure_ai_input(folder, organise_into=None, inbox_kind="General"):
	"""Add an AI Input folder inside `folder`. Files land in the target folder."""
	require_folder(folder, "Edit")
	target = organise_into or folder
	if target != folder:
		require_folder(target, "View")
	existing = frappe.get_all(
		"Drive Folder",
		filters={"parent_drive_folder": folder, "is_ai_inbox": 1, "is_trashed": 0},
		pluck="name",
		limit=1,
	)
	if existing:
		return folder_summary(existing[0])
	doc = create_folder(
		"AI Input",
		parent=folder,
		is_ai_inbox=1,
		inbox_kind=inbox_kind or "General",
		organise_into=target,
	)
	return folder_summary(doc.name)


@frappe.whitelist()
def rename(kind, name, title):
	_require_item(kind, name, "Edit")
	if kind == "folder":
		rename_folder(name, title)
	else:
		rename_file(name, title)
	return {"name": name, "title": title}


@frappe.whitelist()
def move(kind, name, folder):
	_require_item(kind, name, "Edit")
	require_folder(folder, "Edit")
	if kind == "folder":
		move_folder(name, folder)
	else:
		move_file(name, folder)
	return {"name": name, "folder": folder}


@frappe.whitelist()
def trash(kind, name):
	_require_item(kind, name, "Edit")
	if kind == "folder":
		mark_trashed("Drive Folder", name, True)
	else:
		trash_file(name)
	return {"name": name, "trashed": True}


@frappe.whitelist()
def restore(kind, name):
	_require_item(kind, name, "Manage")
	if kind == "folder":
		mark_trashed("Drive Folder", name, False)
	else:
		restore_file(name)
	return {"name": name, "trashed": False}


@frappe.whitelist()
def delete_permanently(kind, name):
	"""Delete the database record only. The S3 object is not removed."""
	_require_item(kind, name, "Manage")
	if kind == "folder":
		delete_folder_record(name)
	else:
		delete_file_record(name)
	return {"name": name, "deleted": True}


def _require_item(kind, name, required):
	if kind == "folder":
		return require_folder(name, required)
	folder = frappe.db.get_value("Drive File", name, "folder")
	if not folder:
		frappe.throw(frappe._("File not found"), frappe.DoesNotExistError)
	level = require_folder(folder, required)
	if not level_at_least(level, required):
		frappe.throw(frappe._("Not permitted"), frappe.PermissionError)
	return level

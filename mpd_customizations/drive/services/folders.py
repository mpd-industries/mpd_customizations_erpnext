"""Folder create, rename, move, and listing."""

import frappe
from frappe.utils import now_datetime

from mpd_customizations.drive.services.access import clear_folder_cache, level_for


def breadcrumbs(folder_name):
	crumbs = []
	current = folder_name
	seen = set()
	while current and current not in seen:
		seen.add(current)
		row = frappe.db.get_value(
			"Drive Folder",
			current,
			["name", "title", "parent_drive_folder"],
			as_dict=True,
		)
		if not row:
			break
		crumbs.append({"name": row.name, "title": row.title})
		current = row.parent_drive_folder
	crumbs.reverse()
	return crumbs


def _existing_fields(fields):
	optional = ("check_duplicates", "purpose", "purpose_custom")
	missing = [field for field in optional if field in fields and not frappe.db.has_column("Drive Folder", field)]
	if not missing:
		return fields
	return [field for field in fields if field not in missing]


def child_folders(folder_name=None, include_trashed=False):
	filters = {}
	if folder_name:
		filters["parent_drive_folder"] = folder_name
	else:
		filters["parent_drive_folder"] = ["is", "not set"]
	if not include_trashed:
		filters["is_trashed"] = 0
	rows = frappe.get_all(
		"Drive Folder",
		filters=filters,
		fields=_existing_fields(
			[
				"name",
				"title",
				"owner",
				"modified",
				"is_ai_inbox",
				"inbox_kind",
				"organise_into",
				"inherit_permissions",
				"parent_drive_folder",
				"check_duplicates",
				"purpose",
				"purpose_custom",
			]
		),
		order_by="title asc",
	)
	return rows


def create_folder(title, parent=None, ignore_permissions=False, **extra):
	doc = frappe.get_doc(
		{
			"doctype": "Drive Folder",
			"title": title,
			"parent_drive_folder": parent,
			"inherit_permissions": extra.get("inherit_permissions", 1),
			"is_ai_inbox": extra.get("is_ai_inbox", 0),
			"inbox_kind": extra.get("inbox_kind") or "General",
			"organise_into": extra.get("organise_into"),
		}
	)
	doc.insert(ignore_permissions=ignore_permissions)
	clear_folder_cache()
	return doc


def get_or_create_child(parent, title, ignore_permissions=False):
	filters = {"parent_drive_folder": parent, "title": title, "is_trashed": 0}
	existing = frappe.db.get_value("Drive Folder", filters, "name")
	if existing:
		return existing
	return create_folder(title, parent=parent, ignore_permissions=ignore_permissions).name


def ensure_path(root_name, segments, ignore_permissions=False):
	"""Create missing folders under root_name. Returns the leaf folder name."""
	current = root_name
	for segment in segments:
		if not segment:
			continue
		current = get_or_create_child(current, segment, ignore_permissions=ignore_permissions)
	return current


def rename_folder(name, title):
	frappe.db.set_value("Drive Folder", name, "title", title)
	clear_folder_cache()


def move_folder(name, new_parent):
	if new_parent == name:
		frappe.throw(frappe._("A folder cannot be moved into itself"))
	# Refuse moving into a descendant.
	current = new_parent
	seen = set()
	while current and current not in seen:
		if current == name:
			frappe.throw(frappe._("A folder cannot be moved into its own subfolder"))
		seen.add(current)
		current = frappe.db.get_value("Drive Folder", current, "parent_drive_folder")
	frappe.db.set_value("Drive Folder", name, "parent_drive_folder", new_parent)
	clear_folder_cache()


def set_sharing(name, rules, inherit):
	doc = frappe.get_doc("Drive Folder", name)
	doc.inherit_permissions = 1 if inherit else 0
	doc.permissions = []
	for rule in rules or []:
		doc.append(
			"permissions",
			{
				"principal_type": rule.get("principal_type"),
				"role": rule.get("role"),
				"user": rule.get("user"),
				"level": rule.get("level") or "View",
			},
		)
	doc.save()
	clear_folder_cache()
	return doc


def mark_trashed(doctype, name, trashed):
	values = {"is_trashed": 1 if trashed else 0, "trashed_on": now_datetime() if trashed else None}
	frappe.db.set_value(doctype, name, values)
	clear_folder_cache()


def folder_summary(name, user=None):
	row = frappe.db.get_value(
		"Drive Folder",
		name,
		_existing_fields(
			[
				"name",
				"title",
				"owner",
				"modified",
				"is_ai_inbox",
				"inbox_kind",
				"organise_into",
				"inherit_permissions",
				"parent_drive_folder",
				"is_trashed",
				"check_duplicates",
				"purpose",
				"purpose_custom",
			]
		),
		as_dict=True,
	)
	if not row:
		return None
	row["level"] = level_for(name, user=user)
	return row

"""Frappe permission hooks. Decisions come from services.permissions."""

import frappe

from mpd_customizations.drive.services.permissions import (
	PTYPE_REQUIRED,
	level_at_least,
	resolve_level,
	roots_for_user,
	visible_names,
)

ADMIN_ROLES = ("System Manager", "Drive Admin")


def _roles(user):
	return set(frappe.get_roles(user))


def is_drive_admin(user=None):
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	return bool(_roles(user) & set(ADMIN_ROLES))


def _folder_index():
	cache = getattr(frappe.local, "_drive_folder_index", None)
	if cache is not None:
		return cache
	rows = frappe.get_all(
		"Drive Folder",
		fields=["name", "owner", "parent_drive_folder", "inherit_permissions", "title", "is_trashed"],
	)
	perms = frappe.get_all(
		"Drive Folder Permission",
		fields=["parent", "principal_type", "role", "user", "level"],
	)
	by_parent = {}
	for perm in perms:
		by_parent.setdefault(perm.parent, []).append(perm)
	index = {}
	for row in rows:
		index[row.name] = {
			"name": row.name,
			"owner": row.owner,
			"parent": row.parent_drive_folder,
			"inherit_permissions": row.inherit_permissions,
			"title": row.title,
			"is_trashed": row.is_trashed,
			"permissions": by_parent.get(row.name, []),
		}
	frappe.local._drive_folder_index = index
	return index


def clear_folder_cache():
	if hasattr(frappe.local, "_drive_folder_index"):
		delattr(frappe.local, "_drive_folder_index")


def level_for(folder_name, user=None):
	user = user or frappe.session.user
	return resolve_level(
		folder_name,
		_folder_index(),
		user,
		_roles(user),
		is_admin=is_drive_admin(user),
	)


def folders_visible_to(user=None, min_level="View"):
	user = user or frappe.session.user
	return visible_names(
		_folder_index(),
		user,
		_roles(user),
		is_admin=is_drive_admin(user),
		min_level=min_level,
	)


def root_folders(user=None):
	user = user or frappe.session.user
	index = _folder_index()
	names = roots_for_user(index, user, _roles(user), is_admin=is_drive_admin(user))
	return [name for name in names if not index[name].get("is_trashed")]


def require_folder(folder_name, required, user=None):
	level = level_for(folder_name, user=user)
	if not level_at_least(level, required):
		frappe.throw(
			frappe._("You do not have {0} access to this folder").format(required), frappe.PermissionError
		)
	return level


def has_folder_permission(doc, ptype="read", user=None):
	user = user or frappe.session.user
	if is_drive_admin(user):
		return True
	required = PTYPE_REQUIRED.get(ptype, "View")
	parent = doc.get("parent_drive_folder") if doc else None
	# A brand new root folder can only be created by an admin.
	if ptype == "create" and not parent and not getattr(doc, "name", None):
		return False
	target = parent if ptype == "create" and parent else (doc.name if doc else None)
	if ptype == "create" and parent:
		target = parent
	level = level_for(target, user=user) if target else None
	return level_at_least(level, required)


def has_file_permission(doc, ptype="read", user=None):
	user = user or frappe.session.user
	if is_drive_admin(user):
		return True
	required = PTYPE_REQUIRED.get(ptype, "View")
	folder = doc.get("folder") if doc else None
	if not folder:
		return False
	return level_at_least(level_for(folder, user=user), required)


def _in_clause(names):
	if not names:
		return "1=0"
	escaped = ", ".join(frappe.db.escape(name) for name in names)
	return escaped


def folder_query(user=None):
	user = user or frappe.session.user
	if is_drive_admin(user):
		return ""
	return f"`tabDrive Folder`.name in ({_in_clause(folders_visible_to(user))})"


def file_query(user=None):
	user = user or frappe.session.user
	if is_drive_admin(user):
		return ""
	return f"`tabDrive File`.folder in ({_in_clause(folders_visible_to(user))})"

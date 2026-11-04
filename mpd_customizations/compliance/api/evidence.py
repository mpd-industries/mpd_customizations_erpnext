"""Attach Drive files to activities without treating the file as the record."""

import frappe

from mpd_customizations.compliance.services.access import require_activity_write, require_manager
from mpd_customizations.drive.services.folders import ensure_path, get_or_create_child
from mpd_customizations.drive.services.uploads import begin_upload, store_bytes


def activity_folder(activity_name):
	activity = frappe.get_doc("Compliance Activity", activity_name)
	settings = frappe.get_single("Compliance Settings")
	root = settings.library_folder
	if not root:
		frappe.throw("Compliance library folder is not configured.")
	domain = activity.domain or "General"
	leaf = ensure_path(root, [domain, activity.title], ignore_permissions=True)
	return leaf


@frappe.whitelist()
def upload_target(activity):
	folder = activity_folder(activity)
	return {"folder": folder}


@frappe.whitelist()
def prepare_upload(activity, file_name, size=0, mime_type=None):
	doc = frappe.get_doc("Compliance Activity", activity)
	require_activity_write(doc)
	folder = activity_folder(activity)
	return begin_upload(folder, file_name, int(size or 0), mime_type)


@frappe.whitelist()
def upload(activity):
	doc = frappe.get_doc("Compliance Activity", activity)
	require_activity_write(doc)
	uploaded = frappe.request.files.get("file") if getattr(frappe, "request", None) else None
	if not uploaded:
		frappe.throw("Choose a file.")
	raw = uploaded.stream.read()
	folder = activity_folder(doc.name)
	plan = begin_upload(folder, uploaded.filename, len(raw), uploaded.mimetype)
	store_bytes(plan["file_id"], raw, uploaded.mimetype)
	return attach(doc.name, plan["file_id"], note=uploaded.filename)


@frappe.whitelist()
def attach(activity, drive_file, note=None):
	doc = frappe.get_doc("Compliance Activity", activity)
	require_activity_write(doc)
	if not frappe.db.exists("Drive File", drive_file):
		frappe.throw("Drive file not found.")
	doc.append(
		"evidence",
		{
			"drive_file": drive_file,
			"note": note,
			"added_by": frappe.session.user,
			"source": "Manual",
		},
	)
	doc.save(ignore_permissions=True)
	return {"name": doc.name, "evidence": len(doc.evidence)}


@frappe.whitelist()
def link_unmatched(name, activity=None, registration=None):
	require_manager()
	row = frappe.get_doc("Compliance Unmatched Evidence", name)
	if activity:
		attach(activity, row.drive_file, note=row.summary)
		row.linked_activity = activity
	if registration:
		reg = frappe.get_doc("Compliance Registration", registration)
		reg.append("evidence", {"drive_file": row.drive_file, "note": row.summary, "source": "Linked"})
		reg.save(ignore_permissions=True)
		row.linked_registration = registration
	if not activity and not registration:
		frappe.throw("Choose an activity or a registration.")
	row.status = "Linked"
	row.save(ignore_permissions=True)
	return {"name": row.name, "status": row.status}


def ensure_child(parent, title):
	return get_or_create_child(parent, title, ignore_permissions=True)

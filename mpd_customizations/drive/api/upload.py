import frappe

from mpd_customizations.drive.services.access import require_folder
from mpd_customizations.drive.services.uploads import (
	begin_upload,
	cancel_upload,
	download_url,
	finish_upload,
	store_bytes,
)


@frappe.whitelist()
def get_upload_url(folder, file_name, size, mime_type=None):
	require_folder(folder, "Edit")
	return begin_upload(folder, file_name, size, mime_type)


@frappe.whitelist()
def receive_upload(file_id):
	"""Accept the file body and store it on S3 from the server."""
	folder = frappe.db.get_value("Drive File", file_id, "folder")
	require_folder(folder, "Edit")
	uploaded = frappe.request.files.get("file") if frappe.request else None
	if not uploaded:
		frappe.throw(frappe._("No file was received"))
	doc = store_bytes(file_id, uploaded.read(), uploaded.mimetype)
	return {"name": doc.name, "status": doc.status, "title": doc.title, "ai_status": doc.ai_status}


@frappe.whitelist()
def confirm_upload(file_id, parts=None):
	folder = frappe.db.get_value("Drive File", file_id, "folder")
	require_folder(folder, "Edit")
	if isinstance(parts, str):
		parts = frappe.parse_json(parts)
	doc = finish_upload(file_id, parts=parts)
	return {"name": doc.name, "status": doc.status, "title": doc.title, "ai_status": doc.ai_status}


@frappe.whitelist()
def abort_upload(file_id):
	folder = frappe.db.get_value("Drive File", file_id, "folder")
	require_folder(folder, "Edit")
	cancel_upload(file_id)
	return {"file_id": file_id, "aborted": True}


@frappe.whitelist()
def get_download_url(file_id, inline=0):
	folder = frappe.db.get_value("Drive File", file_id, "folder")
	require_folder(folder, "View")
	return {"url": download_url(file_id, inline=frappe.utils.cint(inline))}

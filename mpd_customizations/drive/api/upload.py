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
def receive_upload(file_id, allow_copy=0):
	"""Accept the file body and store it on S3 from the server."""
	folder = frappe.db.get_value("Drive File", file_id, "folder")
	require_folder(folder, "Edit")
	uploaded = frappe.request.files.get("file") if frappe.request else None
	if not uploaded:
		frappe.throw(frappe._("No file was received"))
	result = store_bytes(
		file_id,
		uploaded.read(),
		uploaded.mimetype,
		allow_copy=frappe.utils.cint(allow_copy),
	)
	if isinstance(result, dict) and result.get("duplicate"):
		return result
	return {"name": result.name, "status": result.status, "title": result.title, "ai_status": result.ai_status}


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


@frappe.whitelist()
def download_zip(file_ids, folder_title=None):
	"""Download the selected uploaded files as one ZIP."""
	from mpd_customizations.drive.services.archive import ZipLimitError, build_zip, zip_download_name
	from mpd_customizations.drive.services.s3 import get_storage

	if isinstance(file_ids, str):
		file_ids = frappe.parse_json(file_ids)
	rows = []
	seen = set()
	for file_id in file_ids or []:
		if not file_id or file_id in seen:
			continue
		seen.add(file_id)
		doc = frappe.db.get_value(
			"Drive File",
			file_id,
			["name", "folder", "title", "size", "s3_key", "status", "is_trashed"],
			as_dict=True,
		)
		if not doc or doc.is_trashed or doc.status != "Uploaded" or not doc.s3_key:
			continue
		require_folder(doc.folder, "View")
		rows.append({"title": doc.title, "size": doc.size, "key": doc.s3_key})
	if len(rows) < 2:
		frappe.throw(frappe._("Select at least two uploaded files"))
	storage = get_storage()
	try:
		content = build_zip(rows, storage.read_bytes)
	except ZipLimitError as exc:
		frappe.throw(str(exc))
	frappe.response["filename"] = zip_download_name(folder_title)
	frappe.response["filecontent"] = content
	frappe.response["type"] = "download"

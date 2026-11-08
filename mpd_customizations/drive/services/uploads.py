"""Direct-to-S3 upload session handling."""

import uuid

import frappe

from mpd_customizations.drive.services.files import confirm as confirm_file
from mpd_customizations.drive.services.files import create_pending, delete_file_record, set_upload_id
from mpd_customizations.drive.services.s3 import get_storage, upload_plan


def _settings():
	if not frappe.db.exists("Drive Settings", "Drive Settings"):
		return frappe._dict(
			max_upload_size=2048,
			multipart_threshold_mb=100,
			key_prefix="drive",
		)
	return frappe.get_single("Drive Settings")


def begin_upload(folder, file_name, size, mime_type):
	settings = _settings()
	size = int(size or 0)
	max_mb = int(settings.max_upload_size or 0)
	if max_mb and size > max_mb * 1024 * 1024:
		frappe.throw(frappe._("File is larger than the upload limit of {0} MB").format(max_mb))

	storage = get_storage()
	token = uuid.uuid4().hex
	key = storage.key_for(token, file_name)
	plan = upload_plan(size, int(settings.multipart_threshold_mb or 100))
	doc = create_pending(folder, file_name, size, mime_type, key)

	if plan["mode"] == "put":
		return {
			"file_id": doc.name,
			"mode": "put",
			"key": key,
			"url": storage.presign_put(key, mime_type),
			"headers": {"Content-Type": mime_type} if mime_type else {},
		}

	upload_id = storage.start_multipart(key, mime_type)
	set_upload_id(doc.name, upload_id)
	parts = []
	for part in plan["parts"]:
		parts.append(
			{
				"part_number": part["part_number"],
				"start": part["start"],
				"end": part["end"],
				"url": storage.presign_part(key, upload_id, part["part_number"]),
			}
		)
	return {"file_id": doc.name, "mode": "multipart", "key": key, "upload_id": upload_id, "parts": parts}


def store_bytes(file_id, data, content_type=None, allow_copy=False):
	"""Write the file from this server, so the browser does not need S3 CORS.

	When the same bytes are already in a folder the user can see, the pending
	row is removed and nothing is stored, unless the user allowed the copy.
	"""
	from mpd_customizations.drive.services.hashing import find_visible_duplicate, sha256_bytes

	doc = frappe.get_doc("Drive File", file_id)
	if doc.status == "Uploaded":
		return doc
	digest = sha256_bytes(data)
	if not allow_copy:
		existing = find_visible_duplicate(digest, exclude=file_id, folder=doc.folder)
		if existing:
			delete_file_record(file_id)
			return {"duplicate": existing}
	get_storage().put_bytes(doc.s3_key, data, content_type or doc.mime_type)
	doc = finish_upload(file_id, content_hash=digest, duplicate_ok=1 if allow_copy else 0)
	return doc


def finish_upload(file_id, parts=None, content_hash=None, duplicate_ok=0):
	doc = frappe.get_doc("Drive File", file_id)
	if doc.status == "Uploaded":
		return doc
	storage = get_storage()
	if doc.upload_id:
		if not parts:
			frappe.throw(frappe._("Multipart upload is missing part ETags"))
		storage.complete_multipart(doc.s3_key, doc.upload_id, parts)
	head = storage.head(doc.s3_key)
	remote_size = int(head.get("ContentLength") or 0)
	if doc.size and remote_size and abs(remote_size - int(doc.size)) > 1:
		frappe.throw(frappe._("Uploaded size does not match the file that was requested"))
	doc = confirm_file(file_id, size=remote_size or doc.size)
	if content_hash:
		frappe.db.set_value(
			"Drive File",
			doc.name,
			{"content_hash": content_hash, "duplicate_ok": 1 if duplicate_ok else 0},
		)
	else:
		frappe.enqueue(
			"mpd_customizations.drive.services.hashing.hash_uploaded_file",
			queue="long",
			file_name=doc.name,
			enqueue_after_commit=True,
		)
	_maybe_enqueue_inbox(doc)
	return doc


def cancel_upload(file_id):
	doc = frappe.get_doc("Drive File", file_id)
	if doc.status == "Uploaded":
		frappe.throw(frappe._("This file has already been uploaded"))
	if doc.upload_id and doc.s3_key:
		try:
			get_storage().abort_multipart(doc.s3_key, doc.upload_id)
		except Exception:
			frappe.log_error(title="Drive abort upload failed", message=frappe.get_traceback())
	delete_file_record(file_id)


def download_url(file_id, inline=False):
	doc = frappe.get_doc("Drive File", file_id)
	if doc.status != "Uploaded" or not doc.s3_key:
		frappe.throw(frappe._("This file is not available yet"))
	name = doc.original_filename or doc.title
	return get_storage().presign_get(doc.s3_key, file_name=name, inline=bool(inline))


def _maybe_enqueue_inbox(doc):
	folder = frappe.db.get_value(
		"Drive Folder",
		doc.folder,
		["is_ai_inbox", "is_trashed"],
		as_dict=True,
	)
	if not folder or not folder.is_ai_inbox or folder.is_trashed:
		return
	frappe.db.set_value("Drive File", doc.name, "ai_status", "Queued")
	frappe.enqueue(
		"mpd_customizations.drive.ai.inbox.process_inbox_file",
		queue="long",
		file_name=doc.name,
		enqueue_after_commit=True,
	)

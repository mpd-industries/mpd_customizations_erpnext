"""Daily cleanup. Both jobs only remove database rows or abort unfinished uploads."""

import frappe
from frappe.utils import add_to_date, now_datetime

from mpd_customizations.drive.services.files import delete_file_record, delete_folder_record


def cleanup_pending_uploads():
	"""Drop Pending rows older than a day and abort their unfinished multipart uploads."""
	cutoff = add_to_date(now_datetime(), hours=-24)
	rows = frappe.get_all(
		"Drive File",
		filters={"status": "Pending", "creation": ["<", cutoff]},
		fields=["name", "s3_key", "upload_id"],
	)
	storage = None
	for row in rows:
		if row.upload_id and row.s3_key:
			storage = storage or _storage()
			if storage:
				try:
					storage.abort_multipart(row.s3_key, row.upload_id)
				except Exception:
					frappe.log_error(title="Drive abort multipart failed", message=frappe.get_traceback())
		delete_file_record(row.name)
	frappe.db.commit()


def cleanup_trash():
	"""Remove trashed Drive records past the retention window. S3 objects stay."""
	days = 30
	if frappe.db.exists("Drive Settings", "Drive Settings"):
		days = frappe.db.get_single_value("Drive Settings", "trash_retention_days") or 30
	cutoff = add_to_date(now_datetime(), days=-int(days))
	files = frappe.get_all(
		"Drive File",
		filters={"is_trashed": 1, "trashed_on": ["<", cutoff]},
		pluck="name",
	)
	for name in files:
		delete_file_record(name)
	folders = frappe.get_all(
		"Drive Folder",
		filters={"is_trashed": 1, "trashed_on": ["<", cutoff]},
		pluck="name",
	)
	for name in folders:
		if frappe.db.exists("Drive Folder", name):
			delete_folder_record(name)
	frappe.db.commit()


def _storage():
	try:
		from mpd_customizations.drive.services.s3 import get_storage

		return get_storage()
	except Exception:
		frappe.log_error(title="Drive storage unavailable", message=frappe.get_traceback())
		return None

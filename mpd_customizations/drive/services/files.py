"""Drive File records. Deletes remove the database row only."""

import frappe
from frappe.utils import cint, now_datetime

from mpd_customizations.drive.services.search import like_pattern, matches_query

FILE_FIELDS = [
	"name",
	"title",
	"folder",
	"original_filename",
	"status",
	"s3_key",
	"size",
	"mime_type",
	"upload_id",
	"is_trashed",
	"modified",
	"owner",
	"ai_status",
	"ai_document_type",
	"ai_subject",
	"ai_document_date",
	"ai_tags",
	"ai_summary",
	"ai_context",
	"ai_confidence",
	"ai_suggested_path",
	"routed_to_doctype",
	"routed_to_name",
]


def list_files(folder, include_trashed=False, status=None):
	filters = {"folder": folder}
	if not include_trashed:
		filters["is_trashed"] = 0
	if status:
		filters["status"] = status
	return frappe.get_all("Drive File", filters=filters, fields=FILE_FIELDS, order_by="title asc")


def create_pending(folder, file_name, size, mime_type, key):
	doc = frappe.get_doc(
		{
			"doctype": "Drive File",
			"title": file_name,
			"original_filename": file_name,
			"folder": folder,
			"size": size,
			"mime_type": mime_type,
			"s3_key": key,
			"status": "Pending",
		}
	)
	doc.insert()
	return doc


def confirm(name, size=None):
	values = {"status": "Uploaded", "upload_id": None}
	if size is not None:
		values["size"] = size
	frappe.db.set_value("Drive File", name, values)
	return frappe.get_doc("Drive File", name)


def set_upload_id(name, upload_id):
	frappe.db.set_value("Drive File", name, "upload_id", upload_id)


def rename_file(name, title):
	frappe.db.set_value("Drive File", name, "title", title)


def move_file(name, folder):
	frappe.db.set_value("Drive File", name, "folder", folder)


def trash_file(name):
	frappe.db.set_value(
		"Drive File",
		name,
		{"is_trashed": 1, "trashed_on": now_datetime()},
	)


def restore_file(name):
	frappe.db.set_value("Drive File", name, {"is_trashed": 0, "trashed_on": None})


def delete_file_record(name):
	"""Remove the Drive File document. The S3 object is left in place."""
	frappe.delete_doc("Drive File", name, ignore_permissions=True, force=True)


def delete_folder_record(name):
	"""Remove a folder and the file records inside it. S3 objects stay."""
	files = frappe.get_all("Drive File", filters={"folder": name}, pluck="name")
	for file_name in files:
		delete_file_record(file_name)
	children = frappe.get_all("Drive Folder", filters={"parent_drive_folder": name}, pluck="name")
	for child in children:
		delete_folder_record(child)
	frappe.delete_doc("Drive Folder", name, ignore_permissions=True, force=True)


def search_files(
	folder_names,
	query,
	document_type=None,
	subject=None,
	date_from=None,
	date_to=None,
	filename=None,
):
	if not folder_names:
		return []
	filters = {"is_trashed": 0, "status": "Uploaded", "folder": ["in", list(folder_names)]}
	if document_type:
		filters["ai_document_type"] = document_type
	if subject:
		filters["ai_subject"] = subject
	if date_from and date_to:
		filters["ai_document_date"] = ["between", [date_from, date_to]]
	elif date_from:
		filters["ai_document_date"] = [">=", date_from]
	elif date_to:
		filters["ai_document_date"] = ["<=", date_to]
	or_filters = _search_or_filters(query, filename, like_pattern)
	rows = frappe.get_all(
		"Drive File",
		filters=filters,
		or_filters=or_filters or None,
		fields=FILE_FIELDS,
		order_by="modified desc",
		limit=100,
	)
	if filename and query:
		rows = [row for row in rows if matches_query(row, query)]
	return rows


def _search_or_filters(query, filename, like_pattern):
	"""Filename matches the stored name and title. Query also matches summary and tags."""
	if filename:
		pattern = like_pattern(filename)
		return [
			["original_filename", "like", pattern],
			["title", "like", pattern],
		]
	if query:
		pattern = like_pattern(query)
		return [
			["original_filename", "like", pattern],
			["title", "like", pattern],
			["ai_summary", "like", pattern],
			["ai_tags", "like", pattern],
		]
	return None


def recent_files(folder_names, limit=40):
	if not folder_names:
		return []
	return frappe.get_all(
		"Drive File",
		filters={"is_trashed": 0, "status": "Uploaded", "folder": ["in", list(folder_names)]},
		fields=FILE_FIELDS,
		order_by="modified desc",
		limit=cint(limit) or 40,
	)


def needs_review(folder_names):
	if not folder_names:
		return []
	return frappe.get_all(
		"Drive File",
		filters={"is_trashed": 0, "ai_status": "Needs Review", "folder": ["in", list(folder_names)]},
		fields=FILE_FIELDS,
		order_by="modified desc",
	)

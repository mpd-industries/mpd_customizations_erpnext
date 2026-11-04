import frappe

from mpd_customizations.drive.ai.inbox import file_from_review, process_inbox_file, reorganize_folder
from mpd_customizations.drive.services.access import require_folder


def _folder_of(file_id):
	folder = frappe.db.get_value("Drive File", file_id, "folder")
	if not folder:
		frappe.throw(frappe._("File not found"), frappe.DoesNotExistError)
	return folder


@frappe.whitelist()
def accept_filing(file_id, title=None, subject=None, year=None, subfolder=None, use_year=None):
	require_folder(_folder_of(file_id), "Edit")
	doc = file_from_review(
		file_id, title=title, subject=subject, year=year, subfolder=subfolder, use_year=use_year
	)
	return {"name": doc.name, "title": doc.title, "folder": doc.folder, "ai_status": doc.ai_status}


@frappe.whitelist()
def reorganize(folder):
	"""File this folder from each file's AI overview. Files with no overview stay put."""
	require_folder(folder, "Edit")
	return reorganize_folder(folder)


@frappe.whitelist()
def rerun(file_id):
	require_folder(_folder_of(file_id), "Edit")
	frappe.db.set_value("Drive File", file_id, "ai_status", "Queued")
	frappe.enqueue(
		process_inbox_file,
		queue="long",
		file_name=file_id,
		enqueue_after_commit=True,
	)
	return {"name": file_id, "ai_status": "Queued"}

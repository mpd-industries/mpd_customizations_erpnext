"""Content hashes for Drive files. Hashing an object never deletes it."""

import hashlib

import frappe

from mpd_customizations.drive.services.duplicates import pick_duplicate, watched_folder_names
from mpd_customizations.drive.services.folders import breadcrumbs
from mpd_customizations.drive.services.s3 import get_storage

BATCH = 200


def sha256_bytes(data):
	return hashlib.sha256(data or b"").hexdigest()


def folder_path(folder_name):
	return " / ".join(crumb["title"] for crumb in breadcrumbs(folder_name) if crumb.get("title"))


def file_location(folder_name, title):
	"""Full path of a file, including the file name."""
	folder = folder_path(folder_name)
	name = title or "Untitled"
	return f"{folder} / {name}" if folder else name


def watched_ids():
	"""Folders with duplicate check on, plus every folder inside them."""
	if not frappe.db.has_column("Drive Folder", "check_duplicates"):
		return set()
	rows = frappe.get_all(
		"Drive Folder",
		filters={"is_trashed": 0},
		fields=["name", "parent_drive_folder", "check_duplicates"],
	)
	return watched_folder_names(
		[
			{"name": row.name, "parent": row.parent_drive_folder, "check_duplicates": row.check_duplicates}
			for row in rows
		]
	)


def find_visible_duplicate(digest, exclude=None, folder=None):
	"""An uploaded file in a watched folder with this hash, or None.

	Nothing is returned when `folder` is outside a folder that has duplicate check on.
	The match is the content hash, not the file name.
	"""
	if not digest:
		return None
	watched = watched_ids()
	if not watched or (folder and folder not in watched):
		return None
	from mpd_customizations.drive.services.access import folders_visible_to

	visible = set(folders_visible_to() or [])
	if not visible:
		return None
	rows = frappe.get_all(
		"Drive File",
		filters={"content_hash": digest, "is_trashed": 0, "status": "Uploaded"},
		fields=["name", "title", "folder", "content_hash", "is_trashed", "status", "original_filename"],
	)
	visible_rows = [
		row for row in rows if row.folder in visible and row.folder in watched and row.name != exclude
	]
	match = pick_duplicate(visible_rows, allow_copy=False)
	if not match:
		return None
	match_folder = match.folder if hasattr(match, "folder") else match["folder"]
	match_title = match.title if hasattr(match, "title") else match["title"]
	original = match.original_filename if hasattr(match, "original_filename") else match.get("original_filename")
	return {
		"name": match.name if hasattr(match, "name") else match["name"],
		"title": match_title,
		"folder": match_folder,
		"path": file_location(match_folder, match_title),
		"original_filename": original,
	}


def hash_uploaded_file(file_name):
	"""Fill content_hash from S3. Used for multipart uploads and the backfill."""
	doc = frappe.db.get_value(
		"Drive File",
		file_name,
		["name", "s3_key", "content_hash", "status"],
		as_dict=True,
	)
	if not doc or doc.content_hash or doc.status != "Uploaded" or not doc.s3_key:
		return
	try:
		digest = get_storage().sha256(doc.s3_key)
	except Exception:
		frappe.db.set_value("Drive File", file_name, "content_hash", "unavailable")
		frappe.log_error(title=f"Drive hash failed for {file_name}", message=frappe.get_traceback())
		return
	frappe.db.set_value("Drive File", file_name, "content_hash", digest)


def queue_hash_backfill(reset_failures=False):
	if reset_failures:
		frappe.db.sql(
			"""update `tabDrive File` set content_hash='' where content_hash='unavailable'"""
		)
	frappe.enqueue(
		"mpd_customizations.drive.services.hashing.backfill_content_hashes",
		queue="long",
		enqueue_after_commit=True,
	)


def backfill_content_hashes():
	"""Hash uploaded files that have no hash yet. Shared sizes go first."""
	rows = frappe.db.sql(
		"""
		select name, size, s3_key
		from `tabDrive File`
		where status='Uploaded' and ifnull(is_trashed, 0)=0 and ifnull(content_hash, '')=''
		""",
		as_dict=True,
	)
	if not rows:
		return
	counts = {}
	for row in rows:
		counts[row.size] = counts.get(row.size, 0) + 1
	rows.sort(key=lambda row: (0 if counts.get(row.size, 0) > 1 else 1, row.name or ""))
	for row in rows[:BATCH]:
		try:
			hash_uploaded_file(row.name)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.log_error(title=f"Drive hash backfill failed for {row.name}", message=frappe.get_traceback())
	if len(rows) > BATCH:
		frappe.enqueue(
			"mpd_customizations.drive.services.hashing.backfill_content_hashes",
			queue="long",
			enqueue_after_commit=True,
		)

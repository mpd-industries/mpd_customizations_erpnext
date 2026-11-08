"""Read an inbox upload, classify it, and file it when confidence is high enough."""

import base64
import json

import frappe

from mpd_customizations.drive.ai.filing import (
	decide_inbox,
	reorganize_candidates,
	resolve_subfolder,
	select_route,
	suggested_path,
)
from mpd_customizations.drive.ai.purpose import format_outline
from mpd_customizations.drive.services.files import move_file, rename_file
from mpd_customizations.drive.services.folders import ensure_path
from mpd_customizations.mpd_base.ai.llm import call_llm
from mpd_customizations.mpd_base.ai.task_config import get_task_config

TEXT_EXTENSIONS = {".txt", ".csv", ".md", ".json", ".log"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".tif", ".tiff", ".bmp"}


def process_inbox_file(file_name):
	doc = frappe.get_doc("Drive File", file_name)
	folder = frappe.get_doc("Drive Folder", doc.folder)
	if not folder.is_ai_inbox or not folder.organise_into:
		frappe.db.set_value("Drive File", doc.name, "ai_status", "Skipped")
		return

	handler = resolve_inbox_handler(folder.inbox_kind)
	if handler:
		handler(file_name)
		return

	_classify_and_file(doc, folder)


def reorganize_folder(folder_name):
	"""Queue a read of every uploaded file in this folder, then file the confident ones.

	An AI Input is used when this folder has one. Otherwise the folder itself is
	the target, so any folder can be reorganized.
	"""
	inbox_name = resolve_inbox(folder_name)
	target_folder = None
	if inbox_name:
		inbox = frappe.db.get_value(
			"Drive Folder",
			inbox_name,
			["name", "is_ai_inbox", "organise_into", "inbox_kind"],
			as_dict=True,
		)
		if not inbox or not inbox.organise_into:
			frappe.throw(frappe._("Set a target folder on the AI Input before reorganizing"))
	else:
		target_folder = folder_name
	file_names = _reorganize_file_names(folder_name, inbox_name or folder_name)
	ready = _with_overview(file_names)
	for file_name in ready:
		frappe.db.set_value("Drive File", file_name, "ai_status", "Queued")
	if ready:
		frappe.enqueue(
			run_reorganize,
			queue="long",
			file_names=ready,
			inbox_name=inbox_name,
			target_folder=target_folder,
			enqueue_after_commit=True,
		)
	return {"queued": len(ready), "skipped": len(file_names) - len(ready)}


def run_reorganize(file_names, inbox_name=None, target_folder=None):
	for file_name in file_names or []:
		try:
			reorganize_file(file_name, inbox_name, target_folder)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			if frappe.db.exists("Drive File", file_name):
				frappe.db.set_value("Drive File", file_name, "ai_status", "Failed")
				frappe.db.commit()
			frappe.log_error(title=f"Drive reorganize failed for {file_name}", message=frappe.get_traceback())


def reorganize_file(file_name, inbox_name=None, target_folder=None):
	"""Read one library file and file it when confident."""
	doc = frappe.get_doc("Drive File", file_name)
	if inbox_name and frappe.db.exists("Drive Folder", inbox_name):
		inbox = frappe.get_doc("Drive Folder", inbox_name)
		if inbox.is_ai_inbox and inbox.organise_into:
			handler = resolve_inbox_handler(inbox.inbox_kind)
			if handler and doc.folder == inbox.name:
				handler(file_name)
				return
			_classify_and_file(doc, inbox, from_overview=True)
			return
	target = target_folder or doc.folder
	_classify_and_file(
		doc,
		frappe._dict(name=target, organise_into=target, inbox_kind="General", is_ai_inbox=0),
		from_overview=True,
	)


def _classify_and_file(doc, inbox, from_overview=False):
	frappe.db.set_value("Drive File", doc.name, "ai_status", "Processing")
	try:
		if from_overview:
			classification = _classify_overview(doc, inbox)
			if classification is None:
				frappe.db.set_value("Drive File", doc.name, "ai_status", doc.ai_status or "")
				return
			filename_only = False
		else:
			classification, filename_only = _classify(doc, inbox)
		subjects, subfolders = _library_outline(inbox.organise_into)
		settings = _settings()
		decision = decide_inbox(
			{**classification, "inbox_kind": inbox.inbox_kind},
			subjects,
			settings.ai_confidence_threshold or 0.75,
			settings.year_style or "Financial Year",
			frappe.utils.getdate(),
			filename_only=filename_only,
			subfolders_by_subject=subfolders,
			document_text=" ".join(
				part for part in (doc.original_filename, doc.title, doc.ai_summary) if part
			),
		)
		target_title = frappe.db.get_value("Drive Folder", inbox.organise_into, "title")
		path = suggested_path(target_title, decision["subject"], decision["year"], decision["subfolder"])
		_store_ai_fields(doc.name, classification, decision, path, keep_summary=from_overview)
		if decision["auto_file"]:
			source = doc.folder
			leaf = ensure_path(inbox.organise_into, decision["segments"], ignore_permissions=True)
			if decision["title"]:
				rename_file(doc.name, decision["title"])
			move_file(doc.name, leaf)
			doc.reload()
			_route_after_filing(doc, classification)
			from mpd_customizations.drive.services.purpose import refresh_folder_meanings

			refresh_folder_meanings([leaf, source])
	except Exception:
		frappe.db.set_value("Drive File", doc.name, "ai_status", "Failed")
		frappe.log_error(title=f"Drive inbox failed for {doc.name}", message=frappe.get_traceback())
		raise


def resolve_inbox_handler(kind):
	"""Feature hook: drive_inbox_handlers maps an inbox kind to a dotted path."""
	raw = frappe.get_hooks("drive_inbox_handlers") or {}
	mapping = {}
	if isinstance(raw, dict):
		mapping = raw
	elif isinstance(raw, list):
		for item in raw:
			if isinstance(item, dict):
				mapping.update(item)
	path = mapping.get(kind)
	if isinstance(path, list):
		path = path[-1] if path else None
	if not path:
		return None
	return frappe.get_attr(path)


def file_from_review(file_name, title=None, subject=None, year=None, subfolder=None, use_year=None):
	"""Accept or edit a Needs Review suggestion and file the document."""
	doc = frappe.get_doc("Drive File", file_name)
	folder = frappe.get_doc("Drive Folder", doc.folder)
	if not folder.organise_into and doc.ai_status == "Filed":
		# Already filed; the current folder is the destination, so stop.
		return doc
	inbox_name = folder.name if folder.is_ai_inbox else resolve_inbox(folder.name)
	target = frappe.db.get_value("Drive Folder", inbox_name, "organise_into") if inbox_name else None
	if not target:
		target = doc.folder
	subject = subject or doc.ai_subject or "Unsorted"
	if use_year in (False, 0, "0", "false", "False"):
		year = None
	elif not year:
		year = _year_from_path(doc.ai_suggested_path)
	segments = [part for part in (subject, year, subfolder) if part]
	leaf = ensure_path(target, segments, ignore_permissions=True)
	if title:
		rename_file(doc.name, title)
	move_file(doc.name, leaf)
	frappe.db.set_value(
		"Drive File",
		doc.name,
		{"ai_status": "Filed", "ai_subject": subject, "ai_suggested_path": "/".join(segments)},
	)
	doc.reload()
	_route_after_filing(doc, {"document_type": doc.ai_document_type})
	return doc


def resolve_inbox(folder_name):
	"""Return the AI Input that files into this folder, or into one of its parents."""
	if not folder_name or not frappe.db.exists("Drive Folder", folder_name):
		return None
	row = frappe.db.get_value(
		"Drive Folder",
		folder_name,
		["is_ai_inbox", "organise_into", "is_trashed", "parent_drive_folder"],
		as_dict=True,
	)
	if not row or row.is_trashed:
		return None
	if row.is_ai_inbox and row.organise_into:
		return folder_name
	child = frappe.db.get_value(
		"Drive Folder",
		{"parent_drive_folder": folder_name, "is_ai_inbox": 1, "is_trashed": 0},
		"name",
	)
	if child:
		return child
	current = row.parent_drive_folder
	seen = {folder_name}
	while current and current not in seen:
		seen.add(current)
		parent = frappe.db.get_value(
			"Drive Folder",
			current,
			["parent_drive_folder", "is_trashed"],
			as_dict=True,
		)
		if not parent or parent.is_trashed:
			return None
		inbox = frappe.db.get_value(
			"Drive Folder",
			{"parent_drive_folder": current, "is_ai_inbox": 1, "is_trashed": 0, "organise_into": current},
			"name",
		)
		if inbox:
			return inbox
		current = parent.parent_drive_folder
	return None


def _reorganize_file_names(folder_name, inbox_name):
	folders = frappe.get_all(
		"Drive Folder",
		filters={"is_trashed": 0},
		fields=["name", "parent_drive_folder"],
	)
	folder_rows = [{"name": row.name, "parent": row.parent_drive_folder} for row in folders]
	tree = _folder_and_descendants(folder_name, folder_rows)
	if not tree:
		return []
	files = frappe.get_all(
		"Drive File",
		filters={"is_trashed": 0, "folder": ["in", tree]},
		fields=["name", "folder", "status", "is_trashed", "ai_status"],
	)
	return reorganize_candidates(files, folder_rows, folder_name, inbox_name)


def _folder_and_descendants(root, folder_rows):
	children = {}
	for row in folder_rows:
		children.setdefault(row.get("parent"), []).append(row.get("name"))
	found = []
	stack = [root]
	seen = set()
	while stack:
		current = stack.pop()
		if not current or current in seen:
			continue
		seen.add(current)
		found.append(current)
		stack.extend(children.get(current, []))
	return found


def _year_from_path(path):
	parts = [part for part in (path or "").split("/") if part]
	return parts[-1] if parts else None


def _classify(doc, folder):
	settings = _settings()
	limit = int(settings.ai_max_file_mb or 20) * 1024 * 1024
	filename_only = not doc.size or int(doc.size) > limit
	file_data = None
	mime = None
	text = ""
	if not filename_only and doc.s3_key:
		try:
			file_data, mime, text, filename_only = _read_for_model(doc)
		except Exception:
			frappe.log_error(title="Drive inbox could not read file", message=frappe.get_traceback())
			filename_only = True
	config, _params = get_task_config("drive_inbox_classify")
	outline = _outline_text(folder.organise_into)
	user_prompt = (
		f"File name: {doc.original_filename or doc.title}\nExisting folders:\n{outline}\n"
	)
	if text:
		user_prompt += f"\nDocument text:\n{text[:20000]}"
	if filename_only:
		user_prompt += "\nThe file contents were not available. Classify from the file name only and set confidence below 0.5."
	result = call_llm(
		config,
		config.system_prompt,
		user_prompt,
		reference_doctype="Drive File",
		reference_name=doc.name,
		attached_file_data=file_data,
		attached_mime=mime,
		attached_filename=doc.original_filename or doc.title or "document.pdf",
	)
	if not isinstance(result, dict):
		result = {}
	return result, filename_only


def _classify_overview(doc, folder):
	"""File from the stored overview. The file itself is not opened."""
	overview = (doc.ai_summary or "").strip()
	if not overview:
		return None
	config, _params = get_task_config("drive_inbox_classify")
	outline = _outline_text(folder.organise_into)
	user_prompt = (
		f"File name: {doc.original_filename or doc.title}\n"
		f"Existing folders:\n{outline}\n\n"
		f"AI overview:\n{overview}\n"
	)
	result = call_llm(
		config,
		config.system_prompt,
		user_prompt,
		reference_doctype="Drive File",
		reference_name=doc.name,
	)
	return result if isinstance(result, dict) else {}


def _with_overview(file_names):
	if not file_names:
		return []
	rows = frappe.get_all(
		"Drive File",
		filters={"name": ["in", list(file_names)]},
		fields=["name", "ai_summary"],
	)
	return [row.name for row in rows if (row.ai_summary or "").strip()]


def _read_for_model(doc):
	from mpd_customizations.drive.services.s3 import get_storage

	raw = get_storage().read_bytes(doc.s3_key)
	name = (doc.original_filename or doc.title or "").lower()
	ext = name[name.rfind(".") :] if "." in name else ""
	mime = doc.mime_type or ""
	if ext in IMAGE_EXTENSIONS or mime.startswith("image/"):
		raw = _image_to_pdf(raw)
		encoded = base64.b64encode(raw).decode()
		return f"data:application/pdf;base64,{encoded}", "application/pdf", "", False
	if mime == "application/pdf" or ext == ".pdf":
		encoded = base64.b64encode(raw).decode()
		return f"data:application/pdf;base64,{encoded}", "application/pdf", "", False
	if ext in TEXT_EXTENSIONS or mime.startswith("text/"):
		return None, None, raw.decode("utf-8", errors="replace"), False
	if ext == ".xlsx":
		return None, None, _xlsx_text(raw), False
	return None, None, "", True


def _image_to_pdf(raw):
	from mpd_customizations.asset_organizer.ai.apr_file_io import _image_bytes_to_pdf

	return _image_bytes_to_pdf(raw)


def _xlsx_text(raw):
	import io

	import openpyxl

	book = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
	chunks = []
	for sheet in book.worksheets:
		for row in sheet.iter_rows(max_row=40, max_col=12, values_only=True):
			chunks.append(" | ".join("" if cell is None else str(cell) for cell in row))
	return "\n".join(chunks)[:20000]


def _subject_folders(parent):
	subjects, _subfolders = _library_outline(parent)
	return subjects


def _folder_fields():
	fields = ["name", "title"]
	if frappe.db.has_column("Drive Folder", "purpose"):
		fields.append("purpose")
	return fields


def _child_folder_rows(parent):
	return frappe.get_all(
		"Drive Folder",
		filters={"parent_drive_folder": parent, "is_trashed": 0, "is_ai_inbox": 0},
		fields=_folder_fields(),
		order_by="title asc",
	)


def _outline_folders(parent):
	"""Subject folders under the target, each with its meaning and its child folders."""
	if not parent:
		return []
	folders = []
	for row in _child_folder_rows(parent):
		title = (row.title or "").strip()
		if not title:
			continue
		children = []
		for child in _child_folder_rows(row.name):
			child_title = (child.title or "").strip()
			if child_title:
				children.append({"title": child_title, "purpose": child.get("purpose")})
		folders.append({"title": title, "purpose": row.get("purpose"), "children": children})
	return folders


def _library_outline(parent):
	"""Subject titles under the target, and the subfolders that already exist in each."""
	folders = _outline_folders(parent)
	subjects = [folder["title"] for folder in folders]
	subfolders = {folder["title"]: [child["title"] for child in folder["children"]] for folder in folders}
	return subjects, subfolders


def _outline_text(parent):
	return format_outline(_outline_folders(parent))


def group_into_existing_subfolders(root):
	"""Move files into an existing child folder when the file name already names it.

	Does not call the model and does not create folders. A drawing titled
	"Boiler House" that is sitting in Blueprints moves into the Boiler House folder.
	"""
	if not root or not frappe.db.exists("Drive Folder", root):
		return {"moved": 0}
	folders = frappe.get_all(
		"Drive Folder",
		filters={"is_trashed": 0},
		fields=["name", "title", "parent_drive_folder", "is_ai_inbox"],
	)
	by_parent = {}
	for row in folders:
		by_parent.setdefault(row.parent_drive_folder, []).append(row)
	contained = _folder_and_descendants(
		root, [{"name": row.name, "parent": row.parent_drive_folder} for row in folders]
	)
	moved = []
	for folder_name in contained:
		folder = next((row for row in folders if row.name == folder_name), None)
		if not folder or folder.is_ai_inbox:
			continue
		children = [row for row in by_parent.get(folder_name, []) if not row.is_ai_inbox and row.title]
		if not children:
			continue
		names = [row.title for row in children]
		files = frappe.get_all(
			"Drive File",
			filters={"folder": folder_name, "is_trashed": 0, "status": "Uploaded"},
			fields=["name", "title", "original_filename"],
		)
		for doc in files:
			text = f"{doc.title or ''} {doc.original_filename or ''}"
			match = resolve_subfolder(None, names, text)
			if not match:
				continue
			target = next(row for row in children if row.title == match)
			move_file(doc.name, target.name)
			moved.append({"file": doc.name, "title": doc.title, "folder": match})
	return {"moved": len(moved), "files": moved}


def _settings():
	if frappe.db.exists("Drive Settings", "Drive Settings"):
		return frappe.get_single("Drive Settings")
	return frappe._dict(ai_confidence_threshold=0.75, ai_max_file_mb=20, year_style="Financial Year")


def _store_ai_fields(file_name, classification, decision, path, keep_summary=False):
	tags = classification.get("tags") or []
	if isinstance(tags, list):
		tags = ", ".join(str(tag) for tag in tags)
	facts = classification.get("key_facts") or {}
	frappe.db.set_value(
		"Drive File",
		file_name,
		{
			"ai_status": decision["ai_status"],
			"ai_document_type": classification.get("document_type"),
			"ai_subject": decision["subject"],
			"ai_document_date": classification.get("document_date") or None,
			"ai_tags": tags,
			"ai_context": json.dumps(facts) if not isinstance(facts, str) else facts,
			"ai_confidence": decision["confidence"],
			"ai_suggested_path": path,
		},
	)
	if not keep_summary:
		frappe.db.set_value("Drive File", file_name, "ai_summary", classification.get("summary"))


def _route_after_filing(doc, classification):
	if doc.routed_to_name:
		return
	settings = _settings()
	routes = [
		{"document_type": row.document_type, "handler": row.handler, "enabled": row.enabled}
		for row in (settings.get("inbox_routes") or [])
	]
	handler = select_route(classification.get("document_type") or doc.ai_document_type, routes)
	if not handler:
		return
	frappe.enqueue(
		"mpd_customizations.drive.ai.routes.run_route",
		queue="long",
		file_name=doc.name,
		handler=handler,
		enqueue_after_commit=True,
	)

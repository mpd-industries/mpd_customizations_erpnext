"""Create, revise, and apply a Drive reorganize run."""

import json

import frappe

from mpd_customizations.drive.ai.filing import decide_inbox, suggested_path
from mpd_customizations.drive.ai.inbox import (
	_library_outline,
	_outline_text,
	_settings,
	_store_ai_fields,
	resolve_inbox,
	resolve_inbox_handler,
)
from mpd_customizations.drive.ai.reorganize import (
	MAX_FOLLOWUPS,
	build_reorganize_prompt,
	file_payload,
	select_items_to_apply,
)
from mpd_customizations.drive.services.access import require_folder
from mpd_customizations.drive.services.files import move_file, rename_file
from mpd_customizations.drive.services.folders import ensure_path
from mpd_customizations.drive.services.hashing import folder_path
from mpd_customizations.mpd_base.ai.llm import call_llm
from mpd_customizations.mpd_base.ai.task_config import get_task_config

INSTRUCTION_LIMIT = 4000


def _clip(text):
	return (text or "").strip()[:INSTRUCTION_LIMIT]


def _followups(raw):
	if not raw:
		return []
	if isinstance(raw, list):
		return [str(item) for item in raw if str(item).strip()]
	try:
		loaded = json.loads(raw)
	except (TypeError, json.JSONDecodeError):
		return []
	if not isinstance(loaded, list):
		return []
	return [str(item) for item in loaded if str(item).strip()]


def _target_for(folder_name):
	inbox_name = resolve_inbox(folder_name)
	if inbox_name:
		target = frappe.db.get_value("Drive Folder", inbox_name, "organise_into")
		if not target:
			frappe.throw(frappe._("Set a target folder on the AI Input before reorganizing"))
		return inbox_name, target
	return None, folder_name


def start_reorganize(folder, instruction=None, input_mode="Full JSON", preview=1):
	require_folder(folder, "Edit")
	preview = 1 if frappe.utils.cint(preview) else 0
	if input_mode not in ("Full JSON", "Name only"):
		frappe.throw(frappe._("Choose Full JSON or Name only"))
	if input_mode == "Name only" and not preview:
		frappe.throw(frappe._("Name only always needs a review before anything is moved"))
	inbox_name, target = _target_for(folder)
	run = frappe.get_doc(
		{
			"doctype": "Drive Reorganize Run",
			"folder": folder,
			"target_folder": target,
			"inbox": inbox_name,
			"instruction": _clip(instruction),
			"followups": "[]",
			"revision": 1,
			"input_mode": input_mode,
			"preview": preview,
			"status": "Queued",
		}
	)
	run.insert(ignore_permissions=True)
	frappe.enqueue(
		execute_reorganize_run,
		queue="long",
		run_name=run.name,
		enqueue_after_commit=True,
	)
	return {"name": run.name, "status": run.status, "preview": preview}


def execute_reorganize_run(run_name):
	run = frappe.get_doc("Drive Reorganize Run", run_name)
	if run.status in ("Cancelled", "Applied"):
		return
	run.status = "Running"
	run.save(ignore_permissions=True)
	frappe.db.commit()
	try:
		if not run.items:
			_seed_items(run)
		_propose_items(run)
		run.reload()
		if frappe.db.get_value("Drive Reorganize Run", run.name, "status") == "Cancelled":
			return
		run.status = "Ready" if run.preview else "Applied"
		run.save(ignore_permissions=True)
		frappe.db.commit()
	except Exception:
		frappe.db.rollback()
		frappe.db.set_value("Drive Reorganize Run", run_name, "status", "Failed")
		frappe.db.commit()
		frappe.log_error(title=f"Drive reorganize run failed for {run_name}", message=frappe.get_traceback())


def _seed_items(run):
	from mpd_customizations.drive.ai.inbox import _reorganize_file_names, _with_overview

	names = _reorganize_file_names(run.folder, run.inbox or run.folder)
	if run.input_mode != "Name only":
		names = _with_overview(names)
	for file_name in names:
		folder_name = frappe.db.get_value("Drive File", file_name, "folder")
		if run.preview and _compliance_file(folder_name):
			continue
		title = frappe.db.get_value("Drive File", file_name, "title")
		run.append(
			"items",
			{
				"file": file_name,
				"current_folder": folder_name,
				"current_title": title,
				"current_path": folder_path(folder_name),
				"status": "Proposed",
			},
		)
	run.total_count = len(run.items)
	run.done_count = 0
	run.save(ignore_permissions=True)
	frappe.db.commit()


def _compliance_file(folder_name):
	row = frappe.db.get_value(
		"Drive Folder",
		folder_name,
		["is_ai_inbox", "inbox_kind"],
		as_dict=True,
	)
	if not row or not row.is_ai_inbox:
		return False
	return bool(resolve_inbox_handler(row.inbox_kind))


def _propose_items(run):
	followups = _followups(run.followups)
	outline = _outline_text(run.target_folder)
	config, _params = get_task_config("drive_inbox_classify")
	done = 0
	touched = []
	for item in run.items:
		if frappe.db.get_value("Drive Reorganize Run", run.name, "status") == "Cancelled":
			_refresh_touched(touched)
			return
		if item.status == "Applied":
			done += 1
			continue
		try:
			touched.extend(_propose_one(run, item, config, outline, followups) or [])
		except Exception:
			item.status = "Failed"
			frappe.log_error(
				title=f"Drive reorganize failed for {item.file}",
				message=frappe.get_traceback(),
			)
		done += 1
		run.done_count = done
		if frappe.db.get_value("Drive Reorganize Run", run.name, "status") == "Cancelled":
			_refresh_touched(touched)
			return
		run.save(ignore_permissions=True)
		frappe.db.commit()
	_refresh_touched(touched)


def _propose_one(run, item, config, outline, followups):
	doc = frappe.get_doc("Drive File", item.file)
	if not run.preview and _compliance_file(doc.folder):
		handler = resolve_inbox_handler(frappe.db.get_value("Drive Folder", doc.folder, "inbox_kind"))
		if handler:
			handler(doc.name)
			item.status = "Applied"
			return
	fields = {key: doc.get(key) for key in (
		"title",
		"original_filename",
		"ai_document_type",
		"ai_subject",
		"ai_document_date",
		"ai_tags",
		"ai_summary",
		"ai_context",
	)}
	if run.input_mode != "Name only" and not (doc.ai_summary or "").strip():
		item.status = "Skipped"
		return
	previous = _json_or_empty(item.previous_output)
	payload = file_payload(fields, run.input_mode)
	prompt = build_reorganize_prompt(
		fields,
		outline,
		run.instruction,
		run.input_mode,
		followups=followups,
		previous_plan=previous or None,
	)
	item.model_input = json.dumps(payload, default=str, ensure_ascii=False)
	result = call_llm(
		config,
		config.system_prompt,
		prompt,
		reference_doctype="Drive File",
		reference_name=doc.name,
	)
	if not isinstance(result, dict):
		result = {}
	item.model_output = json.dumps(result, default=str, ensure_ascii=False)
	decision, path = _decision_for(doc, run.target_folder, result)
	item.proposed_title = decision["title"] or doc.title
	item.proposed_path = path
	item.proposed_segments = json.dumps(decision["segments"])
	item.confidence = decision["confidence"]
	if run.preview:
		item.status = "Proposed"
		return
	if decision["auto_file"]:
		leaf, source = _apply_move(doc, run.target_folder, decision, result, path)
		item.status = "Applied"
		return [leaf, source]
	_store_ai_fields(doc.name, result, decision, path, keep_summary=bool((doc.ai_summary or "").strip()))
	item.status = "Skipped"


def _decision_for(doc, target_folder, classification):
	subjects, subfolders = _library_outline(target_folder)
	settings = _settings()
	inbox_kind = "General"
	if target_folder:
		kind = frappe.db.get_value("Drive Folder", target_folder, "inbox_kind")
		if kind:
			inbox_kind = kind
	decision = decide_inbox(
		{**classification, "inbox_kind": inbox_kind},
		subjects,
		settings.ai_confidence_threshold or 0.75,
		settings.year_style or "Financial Year",
		frappe.utils.getdate(),
		filename_only=False,
		subfolders_by_subject=subfolders,
		document_text=" ".join(part for part in (doc.original_filename, doc.title, doc.ai_summary) if part),
	)
	target_title = frappe.db.get_value("Drive Folder", target_folder, "title")
	path = suggested_path(target_title, decision["subject"], decision["year"], decision["subfolder"])
	return decision, path


def _apply_move(doc, target_folder, decision, classification, path):
	source = doc.folder
	leaf = ensure_path(target_folder, decision["segments"], ignore_permissions=True)
	if decision["title"]:
		rename_file(doc.name, decision["title"])
	move_file(doc.name, leaf)
	_store_ai_fields(
		doc.name,
		classification,
		decision,
		path,
		keep_summary=bool((doc.ai_summary or "").strip()),
	)
	doc.reload()
	from mpd_customizations.drive.ai.inbox import _route_after_filing

	_route_after_filing(doc, classification)
	return leaf, source


def _refresh_touched(names):
	if not names:
		return
	from mpd_customizations.drive.services.purpose import refresh_folder_meanings

	refresh_folder_meanings(names)


def _json_or_empty(raw):
	if not raw:
		return {}
	try:
		loaded = json.loads(raw)
	except (TypeError, json.JSONDecodeError):
		return {}
	return loaded if isinstance(loaded, dict) else {}


def get_reorganize_run(run_name):
	run = frappe.get_doc("Drive Reorganize Run", run_name)
	require_folder(run.folder, "Edit")
	settings = _settings()
	items = []
	for item in run.items:
		items.append(
			{
				"name": item.name,
				"file": item.file,
				"current_folder": item.current_folder,
				"current_title": item.current_title,
				"current_path": item.current_path,
				"proposed_title": item.proposed_title,
				"proposed_path": item.proposed_path,
				"confidence": item.confidence,
				"status": item.status,
				"model_input": item.model_input,
				"model_output": item.model_output,
			}
		)
	return {
		"name": run.name,
		"status": run.status,
		"preview": run.preview,
		"instruction": run.instruction,
		"followups": _followups(run.followups),
		"revision": run.revision,
		"input_mode": run.input_mode,
		"total_count": run.total_count,
		"done_count": run.done_count,
		"threshold": settings.ai_confidence_threshold or 0.75,
		"items": items,
	}


def apply_reorganize(run_name, item_names):
	run = frappe.get_doc("Drive Reorganize Run", run_name)
	require_folder(run.folder, "Edit")
	if run.status != "Ready":
		frappe.throw(frappe._("This plan is not ready to apply"))
	if isinstance(item_names, str):
		item_names = json.loads(item_names)
	if not item_names:
		frappe.throw(frappe._("Select at least one file"))
	folders_now = {
		item.file: frappe.db.get_value("Drive File", item.file, "folder")
		for item in run.items
	}
	choice = select_items_to_apply(
		[{"name": item.name, "file": item.file, "current_folder": item.current_folder} for item in run.items],
		item_names,
		folders_now,
	)
	by_name = {item.name: item for item in run.items}
	applied = 0
	touched = []
	for name in choice["skip"]:
		by_name[name].status = "Skipped"
	for name in choice["apply"]:
		item = by_name[name]
		if item.status == "Failed" or not item.proposed_segments:
			item.status = "Skipped"
			continue
		try:
			doc = frappe.get_doc("Drive File", item.file)
			classification = _json_or_empty(item.model_output)
			segments = json.loads(item.proposed_segments or "[]")
			decision = {
				"title": item.proposed_title,
				"segments": segments,
				"subject": segments[0] if segments else classification.get("subject"),
				"confidence": item.confidence,
				"ai_status": "Filed",
			}
			leaf, source = _apply_move(doc, run.target_folder, decision, classification, item.proposed_path or "")
			touched.extend([leaf, source])
			item.status = "Applied"
			applied += 1
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			item.status = "Failed"
			frappe.log_error(title=f"Drive apply failed for {item.file}", message=frappe.get_traceback())
	run.status = "Applied"
	run.save(ignore_permissions=True)
	frappe.db.commit()
	_refresh_touched(touched)
	return {"applied": applied, "skipped": len(choice["skip"])}


def revise_reorganize(run_name, followup):
	run = frappe.get_doc("Drive Reorganize Run", run_name)
	require_folder(run.folder, "Edit")
	text = _clip(followup)
	if not text:
		frappe.throw(frappe._("Write a follow-up before redoing the plan"))
	if run.status != "Ready":
		frappe.throw(frappe._("The plan can be revised once it is ready"))
	followups = _followups(run.followups)
	if len(followups) >= MAX_FOLLOWUPS:
		frappe.throw(frappe._("This plan already has 8 follow-ups. Apply it or start a new reorganize."))
	for item in run.items:
		item.previous_output = item.model_output
		item.model_output = None
		item.proposed_title = None
		item.proposed_path = None
		item.proposed_segments = None
		item.confidence = None
		item.status = "Proposed"
	followups.append(text)
	run.followups = json.dumps(followups)
	run.revision = int(run.revision or 1) + 1
	run.status = "Queued"
	run.done_count = 0
	run.save(ignore_permissions=True)
	frappe.enqueue(
		execute_reorganize_run,
		queue="long",
		run_name=run.name,
		enqueue_after_commit=True,
	)
	return {"name": run.name, "status": "Queued", "revision": run.revision}


def cancel_reorganize(run_name):
	run = frappe.get_doc("Drive Reorganize Run", run_name)
	require_folder(run.folder, "Edit")
	if run.status == "Applied":
		frappe.throw(frappe._("This plan has already been applied"))
	run.status = "Cancelled"
	run.save(ignore_permissions=True)
	return {"name": run.name, "status": run.status}


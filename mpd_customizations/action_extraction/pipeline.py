import json
import os

import frappe
from frappe import _

from mpd_customizations.action_extraction.tool_definitions import (
	TASK_UPDATE_TOOLS,
	REOPEN_TOOLS,
	NEW_TASK_TOOLS,
)
from mpd_customizations.action_extraction.prompt import (
	build_speaker_id_prompt,
	build_task_batch_prompt,
	build_new_tasks_prompt,
	resolve_attendees,
)
from mpd_customizations.action_extraction import tools as _tools

BATCH_SIZE = 5

# ─── public entry points ──────────────────────────────────────────────────────

def run_transcription(meeting_note_name):
	doc = frappe.get_doc("Meeting Note", meeting_note_name)
	try:
		_validate_sarvam_key()
		doc.transcript = _transcribe_with_diarization(doc)
		doc.status = "Draft"
		doc.extraction_log = "Transcription completed."
		doc.save(ignore_permissions=True)
		frappe.db.commit()
	except Exception:
		doc.status = "Draft"
		doc.extraction_log = frappe.get_traceback()
		doc.save(ignore_permissions=True)
		frappe.db.commit()
		frappe.log_error(frappe.get_traceback(), f"Meeting Note Transcription Failed: {meeting_note_name}")


def run(meeting_note_name):
	"""
	Pipeline:
	  1. Identify speakers
	  2. Process open tasks in batches of 5
	  3. Extract new tasks + reopen recently-closed ones
	  4. Generate meeting summary
	"""
	doc = frappe.get_doc("Meeting Note", meeting_note_name)
	log_entries = []

	try:
		import litellm

		model, api_key, api_base, extra_headers = _resolve_llm_credentials()

		if not doc.transcript:
			frappe.throw("No transcript found. Run transcription first.")

		attendees = resolve_attendees(doc)
		kwargs = _build_kwargs(model, api_key, api_base, extra_headers)

		# ── Step 1: Identify speakers ────────────────────────────────────────
		speaker_map = _identify_speakers(doc, attendees, litellm, kwargs)
		speaker_map_text = _format_speaker_map(speaker_map, attendees)
		log_entries.append({"step": "speaker_identification", "result": speaker_map})

		frappe.db.set_value("Meeting Note", doc.name, "extraction_log",
			json.dumps({"speaker_map": speaker_map}, indent=2))
		frappe.db.commit()

		# ── Step 2: Fetch all tasks ───────────────────────────────────────────
		backlog = _tools.get_backlog(doc.project)
		open_tasks = backlog["tasks"]
		recent_closed = backlog.get("recently_closed", [])

		log_entries.append({
			"step": "backlog_fetched",
			"open_count": len(open_tasks),
			"closed_count": len(recent_closed),
		})

		# ── Step 3: Process tasks in batches of BATCH_SIZE ───────────────────
		for i in range(0, len(open_tasks), BATCH_SIZE):
			batch = open_tasks[i:i + BATCH_SIZE]
			results = _process_task_batch(batch, doc, attendees, speaker_map_text, litellm, kwargs)
			log_entries.append({
				"step": "task_batch",
				"batch": i // BATCH_SIZE + 1,
				"tasks": [t["name"] for t in batch],
				"result": results,
			})

		# ── Step 4: New tasks + reopen recently-closed ────────────────────────
		result = _extract_and_reopen(open_tasks, recent_closed, doc, attendees, speaker_map_text, litellm, kwargs)
		log_entries.append({"step": "new_tasks_and_reopen", "result": result})

		# ── Step 5: Generate meeting summary ─────────────────────────────────
		summary = _generate_summary(doc, attendees, speaker_map_text, litellm, kwargs)
		log_entries.append({"step": "summary_generated", "length": len(summary)})

		# ── Done ──────────────────────────────────────────────────────────────
		doc.reload()
		doc.extraction_log = json.dumps(log_entries, indent=2, ensure_ascii=False)
		doc.meeting_summary = summary
		doc.status = "Review"
		doc.save(ignore_permissions=True)
		frappe.db.commit()

	except Exception:
		tb = frappe.get_traceback()
		frappe.db.set_value("Meeting Note", meeting_note_name, {
			"status": "Draft",
			"extraction_log": tb,
		})
		frappe.db.commit()
		frappe.log_error(tb, f"Meeting Note Extraction Failed: {meeting_note_name}")


def reset_stuck_jobs():
	import frappe.utils

	cutoff = frappe.utils.add_to_date(frappe.utils.now_datetime(), minutes=-30)
	stuck = frappe.get_all(
		"Meeting Note",
		filters={"status": ["in", ["Processing", "Transcribing"]], "modified": ["<", cutoff]},
		fields=["name"],
	)

	for row in stuck:
		frappe.db.set_value("Meeting Note", row.name, {
			"status": "Draft",
			"extraction_log": "Reset by scheduler: job did not complete within 30 minutes.",
		})
		frappe.log_error(
			f"Meeting Note {row.name} was stuck for >30 min and has been reset.",
			"Meeting Note Stuck Job Reset",
		)

	if stuck:
		frappe.db.commit()


# ─── pipeline steps ───────────────────────────────────────────────────────────

def _identify_speakers(doc, attendees, litellm, kwargs):
	system_prompt = build_speaker_id_prompt(attendees)
	transcript_sample = doc.transcript[:3000]

	try:
		response = litellm.completion(
			messages=[
				{"role": "system", "content": system_prompt},
				{"role": "user", "content": f"Transcript (first portion):\n{transcript_sample}"},
			],
			model=kwargs["model"],
			api_key=kwargs["api_key"],
			api_base=kwargs["api_base"],
			**({"extra_headers": kwargs["extra_headers"]} if kwargs.get("extra_headers") else {}),
			max_tokens=500,
		)
		raw = response.choices[0].message.content or "{}"
		raw = raw.strip().strip("```json").strip("```").strip()
		return json.loads(raw)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Speaker identification failed — continuing without it")
		return {}


def _process_task_batch(tasks, doc, attendees, speaker_map_text, litellm, kwargs):
	"""
	One LLM call for up to BATCH_SIZE tasks.
	LLM calls update_existing_task for each task it finds discussed; skips the rest.
	"""
	system_prompt = build_task_batch_prompt(
		tasks=tasks,
		attendees=attendees,
		speaker_map_text=speaker_map_text,
		meeting_date=str(doc.meeting_date),
	)

	task_details = "\n\n".join(_format_task_for_prompt(t) for t in tasks)
	user_message = (
		f"{task_details}\n\n"
		f"--- FULL TRANSCRIPT ---\n{doc.transcript}\n--- END ---"
	)

	messages = [
		{"role": "system", "content": system_prompt},
		{"role": "user", "content": user_message},
	]

	# Allow up to 4 rounds per task in the batch
	return _run_tool_loop(messages, TASK_UPDATE_TOOLS, litellm, kwargs, max_rounds=len(tasks) * 4)


def _generate_summary(doc, attendees, speaker_map_text, litellm, kwargs):
	attendee_names = ", ".join(a["full_name"] for a in attendees if a.get("full_name")) or "unknown attendees"
	system = (
		"You summarize meeting transcripts. Write a concise 3-6 sentence paragraph covering: "
		"who attended, what was discussed, key decisions made, and any open questions. "
		"Do not list tasks — just summarize the conversation. Plain text, no markdown."
	)
	user = (
		f"Meeting: {doc.title}\nDate: {doc.meeting_date}\nAttendees: {attendee_names}\n"
		f"Speaker map:\n{speaker_map_text}\n\n"
		f"--- TRANSCRIPT ---\n{doc.transcript}\n--- END ---"
	)
	try:
		response = litellm.completion(
			messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
			model=kwargs["model"],
			api_key=kwargs["api_key"],
			api_base=kwargs["api_base"],
			**({"extra_headers": kwargs["extra_headers"]} if kwargs.get("extra_headers") else {}),
			max_tokens=400,
		)
		return (response.choices[0].message.content or "").strip()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Meeting summary generation failed")
		return ""


def _extract_and_reopen(open_tasks, recent_closed, doc, attendees, speaker_map_text, litellm, kwargs):
	system_prompt = build_new_tasks_prompt(
		attendees=attendees,
		speaker_map_text=speaker_map_text,
		meeting_date=str(doc.meeting_date),
	)

	all_tasks = open_tasks + recent_closed
	task_list = "\n".join(
		f"  - {t['name']}: {t['subject']} [status: {t['status']}]"
		for t in all_tasks
	) or "  (no existing tasks)"

	user_message = (
		f"Meeting Title: {doc.title}\n"
		f"Project: {doc.project}\n"
		f"Date: {doc.meeting_date}\n\n"
		f"Existing tasks (do NOT recreate these):\n{task_list}\n\n"
		f"Recently closed tasks that could be reopened:\n"
		+ (
			"\n".join(f"  - {t['name']}: {t['subject']}" for t in recent_closed)
			or "  (none)"
		)
		+ f"\n\n--- FULL TRANSCRIPT ---\n{doc.transcript}\n--- END ---"
	)

	messages = [
		{"role": "system", "content": system_prompt},
		{"role": "user", "content": user_message},
	]

	all_tools = NEW_TASK_TOOLS + REOPEN_TOOLS
	return _run_tool_loop(messages, all_tools, litellm, kwargs, max_rounds=15)


# ─── tool execution ───────────────────────────────────────────────────────────

def _run_tool_loop(messages, tools, litellm, kwargs, max_rounds=5):
	call_kwargs = dict(
		model=kwargs["model"],
		api_key=kwargs["api_key"],
		api_base=kwargs["api_base"],
		tools=tools,
		tool_choice="auto",
	)
	if kwargs.get("extra_headers"):
		call_kwargs["extra_headers"] = kwargs["extra_headers"]

	msg = None
	for _ in range(max_rounds):
		response = litellm.completion(messages=messages, **call_kwargs)
		msg = response.choices[0].message
		messages.append({"role": "assistant", "content": msg.content or "", "tool_calls": msg.tool_calls})

		if not msg.tool_calls:
			break

		for tc in msg.tool_calls:
			fn_name = tc.function.name
			try:
				fn_args = json.loads(tc.function.arguments)
			except json.JSONDecodeError:
				fn_args = {}

			result = _dispatch_tool(fn_name, fn_args)

			messages.append({
				"role": "tool",
				"tool_call_id": tc.id,
				"content": json.dumps(result),
			})

	return (msg.content or "") if msg else ""


def _dispatch_tool(name, args):
	dispatch = {
		"update_existing_task": _tools.update_existing_task,
		"reopen_task": _tools.reopen_task,
		"create_pending_task": _tools.create_pending_task,
		"create_subtask": _tools.create_subtask,
	}
	fn = dispatch.get(name)
	if not fn:
		return {"error": f"Unknown tool: {name}"}
	try:
		return fn(**args)
	except Exception as exc:
		frappe.log_error(frappe.get_traceback(), f"Tool call failed: {name}")
		return {"error": str(exc), "tool": name}


# ─── formatting helpers ───────────────────────────────────────────────────────

def _format_task_for_prompt(task):
	return (
		f"Task: {task['name']}\n"
		f"Subject: {task['subject']}\n"
		f"Status: {task.get('status', 'Open')}\n"
		f"Assigned to: {task.get('assigned_to') or 'Unassigned'}\n"
		f"Due date: {task.get('exp_end_date') or 'Not set'}\n"
		f"Priority: {task.get('priority', 'Medium')}\n"
		f"Description:\n{task.get('description') or '(none)'}"
	)


def _format_speaker_map(speaker_map, attendees):
	if not speaker_map:
		return "(speaker identification was not possible)"

	user_to_name = {a["user_id"]: a["full_name"] for a in attendees if a["user_id"]}
	lines = []
	for label, user_id in sorted(speaker_map.items()):
		if user_id:
			name = user_to_name.get(user_id, user_id)
			lines.append(f"  {label} → {name} ({user_id})")
		else:
			lines.append(f"  {label} → Unknown")
	return "\n".join(lines) if lines else "(no speakers identified)"


# ─── LLM credentials ─────────────────────────────────────────────────────────

def _build_kwargs(model, api_key, api_base, extra_headers):
	return {
		"model": model,
		"api_key": api_key,
		"api_base": api_base,
		"extra_headers": extra_headers or {},
	}


def _resolve_llm_credentials():
	results = frappe.get_all(
		"AI Task Config",
		filters={"task_key": "meeting_note_extraction", "is_active": 1},
		fields=["name"],
		limit=1,
	)
	if results:
		config = frappe.get_doc("AI Task Config", results[0].name)
		provider = frappe.get_doc("LLM Provider", config.llm_provider)
		api_key = provider.get_password("api_key")
		api_base = provider.api_base
		model = config.model
		return model, api_key, api_base, _openrouter_headers(api_base, model)

	api_key = os.environ.get("OPENROUTER_API_KEY") or frappe.conf.get("openrouter_api_key")
	model = (
		os.environ.get("OPENROUTER_MODEL")
		or frappe.conf.get("openrouter_model")
		or "openrouter/anthropic/claude-sonnet-4-6"
	)
	if not api_key:
		frappe.throw(_(
			"Meeting note extraction is not configured. "
			"Options: (1) AI Task Config with task_key='meeting_note_extraction' in ERPNext UI, "
			"(2) env var OPENROUTER_API_KEY, "
			"(3) bench set-config openrouter_api_key YOUR_KEY"
		))
	api_base = "https://openrouter.ai/api/v1"
	return model, api_key, api_base, _openrouter_headers(api_base, model)


def _validate_sarvam_key():
	key = os.environ.get("SARVAM_API_KEY") or frappe.conf.get("sarvam_api_key")
	if not key:
		frappe.throw(_(
			"Sarvam API key not configured. "
			"Set env var SARVAM_API_KEY or run: bench set-config sarvam_api_key YOUR_KEY"
		))


def _openrouter_headers(api_base, model):
	base = (api_base or "").lower()
	m = (model or "").lower()
	if "openrouter.ai" in base or m.startswith("openrouter/"):
		site = frappe.utils.get_url() or "https://localhost"
		return {
			"HTTP-Referer": site,
			"X-Title": "MPD Meeting Notes - Action Extraction",
		}
	return {}


# ─── audio transcription ─────────────────────────────────────────────────────

def _get_audio_bytes(file_url):
	import urllib.parse

	if "generate_file" in file_url or "frappe_s3_attachment" in file_url:
		from frappe_s3_attachment.controller import S3Operations
		params = urllib.parse.parse_qs(urllib.parse.urlparse(file_url).query)
		s3_key = params.get("key", [None])[0]
		if not s3_key:
			frappe.throw(f"Cannot parse S3 key from audio URL: {file_url}")
		s3 = S3Operations()
		settings = frappe.get_doc("S3 File Attachment")
		obj = s3.S3_CLIENT.get_object(Bucket=settings.bucket_name, Key=s3_key)
		return obj["Body"].read(), s3_key.split("/")[-1]

	file_path = frappe.get_site_path(file_url.lstrip("/"))
	with open(file_path, "rb") as f:
		return f.read(), os.path.basename(file_url)


def _transcribe_with_diarization(doc):
	import tempfile
	import os as _os
	from sarvamai import SarvamAI

	api_key = os.environ.get("SARVAM_API_KEY") or frappe.conf.get("sarvam_api_key")
	audio_bytes, filename = _get_audio_bytes(doc.audio_file)

	client = SarvamAI(api_subscription_key=api_key)

	job = client.speech_to_text_job.create_job(
		model="saaras:v3",
		language_code="unknown",
		with_diarization=True,
		mode="codemix",
	)

	with tempfile.TemporaryDirectory() as tmp_dir:
		audio_path = _os.path.join(tmp_dir, filename)
		with open(audio_path, "wb") as f:
			f.write(audio_bytes)

		job.upload_files([audio_path])
		job.start()
		job.wait_until_complete(poll_interval=10, timeout=900)

		if job.is_failed():
			frappe.throw("Sarvam diarization job failed.")

		output_dir = _os.path.join(tmp_dir, "out")
		job.download_outputs(output_dir)

		entries = []
		for fname in _os.listdir(output_dir):
			if not fname.endswith(".json"):
				continue
			with open(_os.path.join(output_dir, fname)) as f:
				data = json.load(f)
			diarized = data.get("diarized_transcript") or {}
			entries.extend(diarized.get("entries", []))

	entries.sort(key=lambda e: e.get("start_time_seconds", 0))

	lines = []
	for entry in entries:
		speaker = entry.get("speaker_id", "?")
		text    = entry.get("transcript", "")
		start   = int(float(entry.get("start_time_seconds", 0)))
		end     = int(float(entry.get("end_time_seconds", 0)))
		ts      = f"{start // 60}:{start % 60:02d}-{end // 60}:{end % 60:02d}"
		lines.append(f"Speaker {speaker} [{ts}]: {text}")

	return "\n".join(lines)

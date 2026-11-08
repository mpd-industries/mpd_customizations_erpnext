"""Pure helpers for a Drive reorganize run. No Frappe or network imports."""

import json

AI_FIELDS = (
	"title",
	"original_filename",
	"ai_document_type",
	"ai_subject",
	"ai_document_date",
	"ai_tags",
	"ai_summary",
	"ai_context",
)
NAME_FIELDS = ("original_filename", "title")
MAX_FOLLOWUPS = 8


def file_payload(file_fields, input_mode):
	"""The JSON object sent for one file."""
	fields = file_fields or {}
	keys = NAME_FIELDS if input_mode == "Name only" else AI_FIELDS
	return {key: fields.get(key) for key in keys}


def build_reorganize_prompt(
	file_fields,
	outline,
	instruction,
	input_mode,
	followups=None,
	previous_plan=None,
):
	"""User message for one file. A blank instruction is left out."""
	payload = file_payload(file_fields, input_mode)
	parts = [f"Existing folders:\n{outline or '(none yet)'}"]
	text = (instruction or "").strip()
	if text:
		parts.append(
			"User instruction:\n"
			f"{text}\n"
			"Follow this when choosing the subject, subfolder, and title."
		)
	if input_mode == "Name only":
		parts.append("You have only the file name. You cannot see the document.")
	else:
		parts.append("File the document from this JSON. Do not assume you can see the document.")
	parts.append("File:\n" + json.dumps(payload, default=str, ensure_ascii=False))
	later = [item.strip() for item in (followups or []) if (item or "").strip()]
	if later:
		parts.append("Previous proposal:\n" + json.dumps(previous_plan or {}, default=str, ensure_ascii=False))
		numbered = "\n".join(f"{index}. {item}" for index, item in enumerate(later, start=1))
		parts.append(
			"Follow-up instructions, in order:\n"
			f"{numbered}\n"
			"Revise the previous proposal. Keep a choice the follow-up does not change, "
			"and replace a choice it rejects."
		)
	return "\n\n".join(parts)


def select_items_to_apply(items, selected, folders_now):
	"""Apply only the chosen items whose file is still in the previewed folder."""
	wanted = set(selected or [])
	folders_now = folders_now or {}
	apply = []
	skip = []
	for item in items or []:
		name = item.get("name")
		if name not in wanted:
			continue
		if folders_now.get(item.get("file")) != item.get("current_folder"):
			skip.append(name)
		else:
			apply.append(name)
	return {"apply": apply, "skip": skip}

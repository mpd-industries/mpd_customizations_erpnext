"""Folder meanings for the filing model. No Frappe imports."""

import json


def purpose_request(title, files, children=None, existing=""):
	"""The JSON the model reads when it writes a folder meaning."""
	payload = {
		"folder": " ".join(str(title or "").split()) or "Untitled",
		"files": [_file_for_purpose(row) for row in (files or [])[:8]],
		"folders_inside": [_child_for_purpose(row) for row in (children or [])[:8]],
	}
	current = " ".join(str(existing or "").split())
	if current:
		payload["current_meaning"] = current
	return payload


def purpose_request_text(title, files, children=None, existing=""):
	return json.dumps(purpose_request(title, files, children, existing), ensure_ascii=False)


def accept_model_purpose(result, limit=320):
	"""The purpose sentence from a model response, or an empty string."""
	if not isinstance(result, dict):
		return ""
	return " ".join(str(result.get("purpose") or "").split())[:limit].rstrip()


def learned_purpose(files, children=None, existing="", keep=False, limit=320):
	"""A short meaning for a folder, learned from the files now inside it.

	A meaning the user wrote is kept. An empty result leaves the previous meaning.
	"""
	current = " ".join((existing or "").split())
	if keep and current:
		return current
	types = []
	notes = []
	seen_types = set()
	seen_notes = set()
	for row in files or []:
		kind = " ".join(str((row or {}).get("document_type") or "").split())
		if kind and kind.casefold() not in seen_types:
			seen_types.add(kind.casefold())
			types.append(kind)
		note = _sentence((row or {}).get("summary"))
		if note and note.casefold() not in seen_notes:
			seen_notes.add(note.casefold())
			notes.append(note)
	parts = []
	if types:
		parts.append(f"Holds {', '.join(types[:4])}.")
	for note in notes[:2]:
		if note.casefold() not in " ".join(parts).casefold():
			parts.append(note if note.endswith((".", "?", "!")) else f"{note}.")
	child_line = _children_line(children)
	if child_line:
		parts.append(child_line)
	if not parts:
		titles = []
		seen_titles = set()
		for row in files or []:
			title = " ".join(str((row or {}).get("title") or "").split())
			if title and title.casefold() not in seen_titles:
				seen_titles.add(title.casefold())
				titles.append(title)
			if len(titles) >= 3:
				break
		if titles:
			parts.append("Files such as " + ", ".join(titles) + ".")
	text = " ".join(parts)[:limit].rstrip()
	return text or current


def format_outline(folders):
	"""Folder list for the filing model, with each folder's meaning when it has one."""
	lines = []
	for folder in folders or []:
		title = " ".join(str((folder or {}).get("title") or "").split())
		if not title:
			continue
		purpose = " ".join(str(folder.get("purpose") or "").split()).rstrip(".")
		children = []
		for child in folder.get("children") or []:
			child_title = " ".join(str((child or {}).get("title") or "").split())
			if child_title:
				children.append({"title": child_title, "purpose": (child or {}).get("purpose")})
		head = f"{title} — {purpose}" if purpose else title
		names = ", ".join(child["title"] for child in children)
		if names:
			head = f"{head}: {names}"
		lines.append(head)
		for child in children:
			child_purpose = " ".join(str(child.get("purpose") or "").split())
			if child_purpose:
				lines.append(f"  {child['title']} — {child_purpose}")
	return "\n".join(lines) if lines else "(none yet)"


def _file_for_purpose(row):
	row = row or {}
	return {
		"title": " ".join(str(row.get("title") or "").split()),
		"document_type": " ".join(str(row.get("document_type") or "").split()),
		"summary": " ".join(str(row.get("summary") or "").split())[:400],
	}


def _child_for_purpose(row):
	row = row or {}
	return {
		"title": " ".join(str(row.get("title") or "").split()),
		"purpose": " ".join(str(row.get("purpose") or "").split())[:240],
	}


def _sentence(text):
	text = " ".join(str(text or "").split())
	if not text:
		return ""
	for mark in (".", "?", "!"):
		index = text.find(mark)
		if 0 < index <= 180:
			return text[: index + 1]
	return text[:160].rstrip(" ,;")


def _children_line(children):
	bits = []
	for child in children or []:
		title = " ".join(str((child or {}).get("title") or "").split())
		if not title:
			continue
		purpose = " ".join(str(child.get("purpose") or "").split()).rstrip(".")
		bits.append(f"{title} ({purpose})" if purpose else title)
		if len(bits) >= 6:
			break
	if not bits:
		return ""
	return "Contains " + ", ".join(bits) + "."

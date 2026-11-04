"""Pure filing decisions for the AI Inbox. No Frappe or network imports."""

from datetime import date, datetime


def year_label(value, style):
	"""Financial year is April-March, labelled like FY 2025-26."""
	if value is None:
		return None
	if isinstance(value, datetime):
		value = value.date()
	if not isinstance(value, date):
		return None
	if style == "Calendar":
		return str(value.year)
	start = value.year if value.month >= 4 else value.year - 1
	return f"FY {start}-{(start + 1) % 100:02d}"


def match_existing_subject(suggested, existing):
	"""Reuse an existing subject folder when the names match, ignoring case."""
	cleaned = (suggested or "").strip()
	if not cleaned:
		return "Unsorted"
	folded = cleaned.casefold()
	for name in existing or []:
		if (name or "").strip().casefold() == folded:
			return name
	return cleaned


def resolve_subfolder(suggested, existing, text=""):
	"""Prefer an existing child folder when the document names it.

	The model often files a drawing as "Blueprints" and leaves the subfolder
	empty. "Boiler House" in the file name is enough to reuse that folder.
	A suggestion that matches nothing is kept, so a genuinely new group is
	still created.
	"""
	names = [name.strip() for name in (existing or []) if (name or "").strip()]
	exact = _exact_folder(suggested, names)
	if exact:
		return exact
	found = _folder_named_in_text(" ".join(part for part in (suggested, text) if part), names)
	if found:
		return found
	cleaned = (suggested or "").strip()
	return cleaned or None


def _exact_folder(suggested, names):
	folded = (suggested or "").strip().casefold()
	if not folded:
		return None
	for name in names:
		if name.casefold() == folded:
			return name
	return None


def _folder_named_in_text(text, names):
	compact = _compact(text)
	if len(compact) < 6:
		return None
	best = None
	best_len = 0
	for name in names:
		needle = _compact(name)
		if len(needle) < 6:
			continue
		stems = [needle]
		if needle.endswith("s"):
			stems.append(needle[:-1])
		if any(stem in compact for stem in stems) and len(needle) > best_len:
			best = name
			best_len = len(needle)
	return best


def _compact(value):
	return "".join(ch for ch in (value or "").casefold() if ch.isalnum())


def effective_confidence(confidence, filename_only=False):
	if filename_only:
		return 0.0
	try:
		return float(confidence)
	except (TypeError, ValueError):
		return 0.0


def reorganize_candidates(files, folders, root, inbox):
	"""Return uploaded files under `root` that are not already being read.

	`folders` is `{name, parent}` for every folder in the tree, including `root`.
	A file inside the AI inbox is included when the inbox sits under `root`.
	"""
	parents = {row.get("name"): row.get("parent") for row in folders or []}
	parents.setdefault(root, None)
	parents.setdefault(inbox, None)

	def contained(folder, ancestor):
		seen = set()
		current = folder
		while current and current not in seen:
			if current == ancestor:
				return True
			seen.add(current)
			current = parents.get(current)
		return False

	names = []
	for row in files or []:
		if row.get("is_trashed") or row.get("status") != "Uploaded":
			continue
		if row.get("ai_status") in ("Queued", "Processing"):
			continue
		if not contained(row.get("folder"), root):
			continue
		names.append(row.get("name"))
	return names


def suggested_path(target_title, subject, year, subfolder=None):
	parts = [target_title or "", subject or "Unsorted", year or ""]
	if subfolder:
		parts.append(subfolder)
	return "/".join(part for part in parts if part)


def decide_inbox(
	classification,
	existing_subjects,
	threshold,
	year_style,
	today,
	filename_only=False,
	subfolders_by_subject=None,
	document_text="",
):
	"""Decide whether to auto-file and which folder segments to use.

	A year folder is added only when the model sets use_year and names a document
	date. A missing date does not fall back to today.
	"""
	confidence = effective_confidence(classification.get("confidence"), filename_only=filename_only)
	use_year = classification.get("use_year") in (True, 1, "1", "true", "True")
	year = None
	doc_date = _coerce_date(classification.get("document_date"))
	if use_year and doc_date:
		year = year_label(doc_date, year_style)
	subject = match_existing_subject(classification.get("subject"), existing_subjects)
	children = _children_for(subject, subfolders_by_subject)
	subfolder = resolve_subfolder(
		classification.get("subfolder"),
		children,
		" ".join(part for part in (document_text, classification.get("title")) if part),
	)
	auto = confidence >= float(threshold)
	return {
		"auto_file": auto,
		"ai_status": "Filed" if auto else "Needs Review",
		"confidence": confidence,
		"subject": subject,
		"year": year,
		"subfolder": subfolder,
		"use_year": bool(year),
		"title": (classification.get("title") or "").strip() or None,
		"segments": [part for part in (subject, year, subfolder) if part],
	}


APR_HANDLER = "mpd_customizations.drive.ai.routes.create_asset_procurement_record"


def select_route(document_type, routes):
	wanted = (document_type or "").strip().casefold()
	if not wanted:
		return None
	for route in routes or []:
		if not route.get("enabled"):
			continue
		if (route.get("document_type") or "").strip().casefold() == wanted:
			return route.get("handler")
	return None


def s3_file_url(key, file_name=None):
	from urllib.parse import urlencode

	params = {"key": key}
	if file_name:
		params["file_name"] = file_name
	return "/api/method/frappe_s3_attachment.controller.generate_file?" + urlencode(params)


def _children_for(subject, subfolders_by_subject):
	mapping = subfolders_by_subject or {}
	if subject in mapping:
		return mapping[subject]
	folded = (subject or "").casefold()
	for name, children in mapping.items():
		if (name or "").casefold() == folded:
			return children
	return []


def _coerce_date(value):
	if isinstance(value, datetime):
		return value.date()
	if isinstance(value, date):
		return value
	if not value or not isinstance(value, str):
		return None
	try:
		return datetime.strptime(value[:10], "%Y-%m-%d").date()
	except ValueError:
		return None

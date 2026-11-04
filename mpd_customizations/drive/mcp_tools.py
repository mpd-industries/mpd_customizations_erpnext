"""MCP tools for Drive and compliance. Schemas are plain data so tests can import them."""

TOOL_DEFINITIONS = [
	{
		"type": "function",
		"function": {
			"name": "drive_search",
			"description": "Search files the current user can see by title, filename, summary, or tags.",
			"parameters": {
				"type": "object",
				"properties": {
					"query": {"type": "string", "description": "Matches title, filename, summary, and tags."},
					"filename": {
						"type": "string",
						"description": "Matches the original filename or title only.",
					},
					"document_type": {"type": "string"},
					"subject": {"type": "string"},
					"year": {"type": "string", "description": "Folder year label, e.g. FY 2025-26 or 2026."},
					"date_from": {"type": "string"},
					"date_to": {"type": "string"},
				},
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "drive_get_document",
			"description": "Full summary, key facts, folder path, and a short-lived download URL for one Drive file.",
			"parameters": {
				"type": "object",
				"properties": {"file_id": {"type": "string"}},
				"required": ["file_id"],
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "drive_list_folder",
			"description": "List folders and files in a Drive folder. Pass a folder id, or omit it for the top level.",
			"parameters": {
				"type": "object",
				"properties": {"folder": {"type": "string"}},
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "drive_list_review",
			"description": "Files still waiting in an AI inbox because confidence was too low to file them.",
			"parameters": {"type": "object", "properties": {}},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "drive_accept_filing",
			"description": "File a Needs Review document. Set use_year false to skip the year folder.",
			"parameters": {
				"type": "object",
				"properties": {
					"file_id": {"type": "string"},
					"title": {"type": "string"},
					"subject": {"type": "string"},
					"year": {"type": "string"},
					"subfolder": {"type": "string"},
					"use_year": {"type": "boolean"},
				},
				"required": ["file_id"],
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "drive_folder_tree",
			"description": "Breadcrumb and child folders for one Drive folder. Omit folder for the top level.",
			"parameters": {"type": "object", "properties": {"folder": {"type": "string"}}},
		},
	},
]

MCP_TOOL_SCHEMAS = [
	{
		"name": tool["function"]["name"],
		"description": tool["function"]["description"],
		"inputSchema": tool["function"]["parameters"],
	}
	for tool in TOOL_DEFINITIONS
]

DRIVE_TOOL_NAMES = {tool["function"]["name"] for tool in TOOL_DEFINITIONS}
TOOL_NAMES = DRIVE_TOOL_NAMES
MCP_PROMPTS = []


def filter_documents(
	rows,
	allowed_folders,
	query=None,
	filename=None,
	document_type=None,
	subject=None,
	year=None,
	date_from=None,
	date_to=None,
):
	"""Keep rows whose folder the caller can see, then apply the search filters."""
	allowed = set(allowed_folders or [])
	matched = []
	needle = (query or "").casefold()
	for row in rows or []:
		if row.get("folder") not in allowed:
			continue
		if document_type and (row.get("ai_document_type") or "").casefold() != document_type.casefold():
			continue
		if subject and (row.get("ai_subject") or "").casefold() != subject.casefold():
			continue
		if year and year not in (row.get("ai_suggested_path") or ""):
			continue
		doc_date = row.get("ai_document_date") or ""
		if date_from and doc_date and str(doc_date) < date_from:
			continue
		if date_to and doc_date and str(doc_date) > date_to:
			continue
		if filename:
			names = f"{row.get('original_filename') or ''} {row.get('title') or ''}".casefold()
			if filename.casefold() not in names:
				continue
		if needle:
			haystack = " ".join(
				str(row.get(field) or "") for field in ("title", "ai_summary", "ai_tags", "original_filename")
			).casefold()
			if needle not in haystack:
				continue
		matched.append(row)
	return matched


def dispatch_tool(name, arguments):
	arguments = arguments or {}
	if name == "drive_search":
		return _drive_search(**arguments)
	if name == "drive_get_document":
		return _drive_get_document(**arguments)
	if name == "drive_list_folder":
		return _drive_list_folder(**arguments)
	if name == "drive_list_review":
		return _drive_list_review()
	if name == "drive_accept_filing":
		return _drive_accept_filing(**arguments)
	if name == "drive_folder_tree":
		return _drive_folder_tree(**arguments)
	raise ValueError(f"Unknown tool: {name}")


def _drive_search(
	query=None,
	filename=None,
	document_type=None,
	subject=None,
	year=None,
	date_from=None,
	date_to=None,
):
	from mpd_customizations.drive.api.browse import search

	result = search(
		query=query,
		filename=filename,
		document_type=document_type,
		subject=subject,
		date_from=date_from,
		date_to=date_to,
	)
	files = result["files"]
	if year:
		files = [row for row in files if year in (row.get("ai_suggested_path") or "")]
	return {"files": [_public_file(row) for row in files]}


def _drive_get_document(file_id):
	import frappe

	from mpd_customizations.drive.services.access import require_folder
	from mpd_customizations.drive.services.folders import breadcrumbs
	from mpd_customizations.drive.services.uploads import download_url

	folder = frappe.db.get_value("Drive File", file_id, "folder")
	require_folder(folder, "View")
	doc = frappe.get_doc("Drive File", file_id)
	return {
		"file": _public_file(doc.as_dict()),
		"path": " / ".join(crumb["title"] for crumb in breadcrumbs(folder)),
		"download_url": download_url(file_id, inline=True),
	}


def _drive_list_folder(folder=None):
	from mpd_customizations.drive.api.browse import list_folder

	return list_folder(folder=folder or None)


def _drive_list_review():
	from mpd_customizations.drive.services.access import folders_visible_to
	from mpd_customizations.drive.services.files import needs_review

	rows = needs_review(folders_visible_to())
	return {"files": [_public_file(row) for row in rows]}


def _drive_accept_filing(file_id, title=None, subject=None, year=None, subfolder=None, use_year=None):
	from mpd_customizations.drive.api.inbox import accept_filing

	return accept_filing(
		file_id, title=title, subject=subject, year=year, subfolder=subfolder, use_year=use_year
	)


def _drive_folder_tree(folder=None):
	from mpd_customizations.drive.api.browse import list_folder
	from mpd_customizations.drive.services.folders import breadcrumbs

	listing = list_folder(folder=folder or None)
	path = breadcrumbs(folder) if folder else []
	return {"path": path, "folders": listing.get("folders"), "files": listing.get("files")}


def _public_file(row):
	return {
		"name": row.get("name"),
		"title": row.get("title"),
		"folder": row.get("folder"),
		"ai_document_type": row.get("ai_document_type"),
		"ai_subject": row.get("ai_subject"),
		"ai_document_date": str(row.get("ai_document_date") or "") or None,
		"ai_summary": row.get("ai_summary"),
		"ai_tags": row.get("ai_tags"),
		"ai_context": row.get("ai_context"),
		"ai_suggested_path": row.get("ai_suggested_path"),
		"ai_status": row.get("ai_status"),
		"original_filename": row.get("original_filename"),
	}

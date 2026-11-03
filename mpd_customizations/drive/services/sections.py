"""Split the library into Drive, AI, and Statutory compliance.

Pure data. Callers pass folder rows they have already filtered for access.
"""


def _flag(value):
	return value in (1, True, "1")


def _brief(row):
	return {
		"name": row["name"],
		"title": row.get("title") or "",
		"kind": "folder",
		"is_ai_inbox": 1 if _flag(row.get("is_ai_inbox")) else 0,
		"inbox_kind": row.get("inbox_kind") or "General",
	}


def group_library(rows):
	"""Return sidebar entries and a membership map for every folder name.

	membership[name] = {"section": "drive"|"ai"|"compliance", "anchor": folder name}
	The anchor is the sidebar item that should stay selected while browsing inside it.
	"""
	by_name = {row["name"]: row for row in rows}
	compliance = set()
	for row in rows:
		kind = row.get("inbox_kind") or "General"
		statutory_inbox = _flag(row.get("is_ai_inbox")) and kind in ("Compliance", "Statutory Compliance")
		statutory_root = not row.get("parent_drive_folder") and row.get("title") in (
			"Compliance",
			"Statutory Compliance",
		)
		if not statutory_inbox and not statutory_root:
			continue
		compliance.add(row["name"])
		for key in ("organise_into", "parent_drive_folder"):
			if row.get(key):
				compliance.add(row[key])

	changed = True
	while changed:
		changed = False
		for row in rows:
			parent = row.get("parent_drive_folder")
			if parent in compliance and row["name"] not in compliance:
				compliance.add(row["name"])
				changed = True

	ai = set()
	for row in rows:
		if row["name"] in compliance:
			continue
		if _flag(row.get("is_ai_inbox")):
			ai.add(row["name"])

	changed = True
	while changed:
		changed = False
		for row in rows:
			parent = row.get("parent_drive_folder")
			if parent in ai and row["name"] not in ai and row["name"] not in compliance:
				ai.add(row["name"])
				changed = True

	def anchor(name, section_ids):
		"""Top folder of this section, so the sidebar item stays selected."""
		current = name
		seen = set()
		top = name
		while current and current not in seen:
			seen.add(current)
			if current in section_ids:
				top = current
			row = by_name.get(current)
			parent = row.get("parent_drive_folder") if row else None
			if not parent or parent not in section_ids:
				return top
			current = parent
		return top

	drive_roots = {
		row["name"]
		for row in rows
		if not row.get("parent_drive_folder") and row["name"] not in compliance and row["name"] not in ai
	}
	membership = {}
	for row in rows:
		name = row["name"]
		if name in compliance:
			membership[name] = {"section": "compliance", "anchor": anchor(name, compliance)}
		elif name in ai:
			membership[name] = {"section": "ai", "anchor": anchor(name, ai)}
		else:
			membership[name] = {"section": "drive", "anchor": anchor(name, drive_roots)}

	drive = [
		_brief(row)
		for row in rows
		if not row.get("parent_drive_folder") and membership[row["name"]]["section"] == "drive"
	]
	ai_folders = [
		_brief(row)
		for row in rows
		if _flag(row.get("is_ai_inbox")) and membership[row["name"]]["section"] == "ai"
	]
	compliance_folders = [
		_brief(row)
		for row in rows
		if not row.get("parent_drive_folder") and membership[row["name"]]["section"] == "compliance"
	]

	def by_title(row):
		return row["title"].lower()

	return {
		"drive": sorted(drive, key=by_title),
		"ai": sorted(ai_folders, key=by_title),
		"compliance": sorted(compliance_folders, key=by_title),
		"membership": membership,
	}

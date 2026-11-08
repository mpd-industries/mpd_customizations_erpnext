"""Group Drive files that share a content hash. No Frappe imports."""


def watched_folder_names(folders):
	"""Folder ids where duplicate check is on, including everything inside them.

	`folders` are dicts with name, parent, and check_duplicates. A folder that
	is not checked, and is not inside a checked folder, is left out.
	"""
	children = {}
	checked = []
	for row in folders or []:
		name = row.get("name")
		children.setdefault(row.get("parent"), []).append(name)
		if row.get("check_duplicates"):
			checked.append(name)
	found = set()
	stack = list(checked)
	while stack:
		current = stack.pop()
		if not current or current in found:
			continue
		found.add(current)
		stack.extend(children.get(current) or [])
	return found


def pick_duplicate(rows, allow_copy=False):
	"""The first uploaded file the caller already matched, unless a copy is allowed."""
	if allow_copy:
		return None
	for row in rows or []:
		if row.get("is_trashed") or row.get("status") != "Uploaded":
			continue
		return row
	return None


def duplicate_groups(files):
	"""Groups of identical files, largest wasted space first.

	A pair marked duplicate_ok is hidden. One new unmarked copy of that pair
	shows the group again, so the new copy can be reviewed.
	"""
	buckets = {}
	for row in files or []:
		digest = (row.get("content_hash") or "").strip()
		if not digest or digest == "unavailable":
			continue
		buckets.setdefault(digest, []).append(row)
	groups = []
	for digest, rows in buckets.items():
		if len(rows) < 2:
			continue
		if all(row.get("duplicate_ok") for row in rows):
			continue
		size = int(rows[0].get("size") or 0)
		groups.append(
			{
				"content_hash": digest,
				"files": rows,
				"wasted_bytes": (len(rows) - 1) * size,
			}
		)
	groups.sort(key=lambda group: group["wasted_bytes"], reverse=True)
	return groups

"""Folder access levels. No database access, so unit tests can import this directly."""

LEVEL_RANK = {"View": 1, "Edit": 2, "Manage": 3}
RANK_LEVEL = {1: "View", 2: "Edit", 3: "Manage"}

PTYPE_REQUIRED = {
	"read": "View",
	"select": "View",
	"write": "Edit",
	"create": "Edit",
	"delete": "Manage",
	"share": "Manage",
	"export": "View",
	"print": "View",
	"email": "View",
	"report": "View",
}


def level_at_least(level, required):
	if not level or not required:
		return False
	return LEVEL_RANK.get(level, 0) >= LEVEL_RANK.get(required, 99)


def _rule_rank(folder, user, roles):
	best = 0
	if folder.get("owner") == user:
		best = LEVEL_RANK["Manage"]
	for rule in folder.get("permissions") or []:
		rank = LEVEL_RANK.get(rule.get("level") or "", 0)
		if not rank:
			continue
		principal = rule.get("principal_type")
		if principal == "User" and rule.get("user") == user:
			best = max(best, rank)
		elif principal == "Role" and rule.get("role") in roles:
			best = max(best, rank)
	return best


def resolve_level(folder_name, folders_by_name, user, roles, is_admin=False):
	"""Highest level for `user` on `folder_name`.

	Rules are collected from the folder, then each ancestor, and stop at the
	first folder whose inherit_permissions flag is off (that folder's own
	rules are still included).
	"""
	if is_admin:
		return "Manage"
	if not folder_name:
		return None

	best = 0
	current = folder_name
	seen = set()
	while current and current not in seen:
		seen.add(current)
		folder = folders_by_name.get(current)
		if not folder:
			break
		best = max(best, _rule_rank(folder, user, roles))
		if not folder.get("inherit_permissions"):
			break
		current = folder.get("parent")
	return RANK_LEVEL.get(best)


def visible_names(folders_by_name, user, roles, is_admin=False, min_level="View"):
	"""Folder names the user can access at min_level or above."""
	visible = []
	for name in folders_by_name:
		level = resolve_level(name, folders_by_name, user, roles, is_admin=is_admin)
		if level_at_least(level, min_level):
			visible.append(name)
	return visible


def roots_for_user(folders_by_name, user, roles, is_admin=False):
	"""Top-level entries: visible folders whose parent is missing or not visible."""
	visible = set(visible_names(folders_by_name, user, roles, is_admin=is_admin))
	roots = []
	for name in visible:
		parent = (folders_by_name.get(name) or {}).get("parent")
		if not parent or parent not in visible:
			roots.append(name)
	return roots

"""Search matching that does not need a Frappe site."""


def like_pattern(value):
	"""LIKE pattern with % and _ treated as literal characters."""
	text = str(value or "")
	text = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
	return f"%{text}%"


def matches_filename(row, filename):
	needle = (filename or "").casefold().strip()
	if not needle:
		return True
	blob = f"{row.get('original_filename') or ''} {row.get('title') or ''}".casefold()
	return needle in blob


def matches_query(row, query):
	needle = (query or "").casefold().strip()
	if not needle:
		return True
	blob = " ".join(
		str(row.get(field) or "") for field in ("title", "original_filename", "ai_summary", "ai_tags")
	).casefold()
	return needle in blob

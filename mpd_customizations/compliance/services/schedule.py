"""Pure period generation. No Frappe imports."""

from calendar import monthrange
from datetime import date, datetime, timedelta

FREQUENCIES = ("Monthly", "Quarterly", "Half-yearly", "Yearly", "Expiry-based")


def _as_date(value):
	if isinstance(value, datetime):
		return value.date()
	if isinstance(value, date):
		return value
	if isinstance(value, str) and value:
		try:
			return datetime.strptime(value[:10], "%Y-%m-%d").date()
		except ValueError:
			return None
	return None


def _clamp(year, month, day):
	return date(year, month, min(int(day), monthrange(year, month)[1]))


def _shift_month(year, month, offset):
	index = year * 12 + (month - 1) + int(offset or 0)
	return index // 12, index % 12 + 1


def _month_span(year, month):
	last = monthrange(year, month)[1]
	return date(year, month, 1), date(year, month, last)


def _iter_months(start, end):
	cursor = date(start.year, start.month, 1)
	last = date(end.year, end.month, 1)
	while cursor <= last:
		yield cursor.year, cursor.month
		year, month = _shift_month(cursor.year, cursor.month, 1)
		cursor = date(year, month, 1)


def _fy_start(day):
	return day.year if day.month >= 4 else day.year - 1


def _fy_label(start_year):
	return f"FY {start_year}-{(start_year + 1) % 100:02d}"


def _override_for(period_end, overrides):
	for row in overrides or []:
		try:
			month = int(row.get("month") or 0)
		except (TypeError, ValueError):
			continue
		if month == period_end.month:
			return row
	return None


def due_on(period_end, due_day, due_month_offset, overrides=None):
	row = _override_for(period_end, overrides)
	day = due_day
	offset = due_month_offset
	if row:
		if row.get("due_day") not in (None, ""):
			day = row.get("due_day")
		if row.get("due_month_offset") not in (None, ""):
			offset = row.get("due_month_offset")
	year, month = _shift_month(period_end.year, period_end.month, offset or 0)
	return _clamp(year, month, day or period_end.day)


def _label_month(start):
	return start.strftime("%b %Y")


def _quarters(basis, start, end):
	"""Yield (label, start, end) covering the window."""
	if basis == "Calendar":
		first = date(start.year, ((start.month - 1) // 3) * 3 + 1, 1)
	else:
		fy = _fy_start(start)
		quarter_index = (start.month - 4) % 12 // 3
		year, month = _shift_month(fy, 4, quarter_index * 3)
		first = date(year, month, 1)
	cursor = first
	while cursor <= end:
		year, month = _shift_month(cursor.year, cursor.month, 2)
		_, period_end = _month_span(year, month)
		if basis == "Calendar":
			quarter = (cursor.month - 1) // 3 + 1
			label = f"{cursor.year} Q{quarter}"
		else:
			fy = _fy_start(cursor)
			quarter = (cursor.month - 4) % 12 // 3 + 1
			label = f"{_fy_label(fy)} Q{quarter}"
		yield label, cursor, period_end
		year, month = _shift_month(cursor.year, cursor.month, 3)
		cursor = date(year, month, 1)


def _halves(basis, start, end):
	if basis == "Financial Year":
		fy = _fy_start(start)
		cursor = date(fy, 4, 1) if start.month >= 4 or start.month <= 3 else date(fy, 4, 1)
		if start.month >= 10 or start.month <= 3:
			# H2 starts October of the FY
			if start >= date(fy, 10, 1) or start.month <= 3:
				cursor = date(fy, 10, 1)
			else:
				cursor = date(fy, 4, 1)
		else:
			cursor = date(fy, 4, 1)
	else:
		cursor = date(start.year, 1 if start.month <= 6 else 7, 1)
	while cursor <= end:
		year, month = _shift_month(cursor.year, cursor.month, 5)
		_, period_end = _month_span(year, month)
		if basis == "Financial Year":
			fy = _fy_start(cursor)
			half = 1 if cursor.month == 4 else 2
			label = f"{_fy_label(fy)} H{half}"
		else:
			half = 1 if cursor.month == 1 else 2
			label = f"{cursor.year} H{half}"
		yield label, cursor, period_end
		year, month = _shift_month(cursor.year, cursor.month, 6)
		cursor = date(year, month, 1)


def _years(basis, start, end):
	if basis == "Financial Year":
		cursor_year = _fy_start(start)
		while date(cursor_year, 4, 1) <= end:
			period_start = date(cursor_year, 4, 1)
			period_end = date(cursor_year + 1, 3, 31)
			yield _fy_label(cursor_year), period_start, period_end
			cursor_year += 1
	else:
		for year in range(start.year, end.year + 1):
			yield str(year), date(year, 1, 1), date(year, 12, 31)


def occurrences(obligation, window_start, window_end, valid_to=None):
	"""Return periods whose due date falls inside the window.

	obligation keys: frequency, period_basis, due_day, due_month_offset,
	effective_from, effective_to, schedule_overrides.
	"""
	window_start = _as_date(window_start)
	window_end = _as_date(window_end)
	if window_start is None or window_end is None or window_end < window_start:
		return []
	frequency = obligation.get("frequency") or "Monthly"
	if frequency in ("One-time", "Event-driven"):
		return []
	effective_from = _as_date(obligation.get("effective_from"))
	effective_to = _as_date(obligation.get("effective_to"))
	basis = obligation.get("period_basis") or "Financial Year"
	due_day = int(obligation.get("due_day") or 20)
	offset = int(obligation.get("due_month_offset") if obligation.get("due_month_offset") is not None else 1)
	overrides = obligation.get("schedule_overrides") or []

	if frequency == "Expiry-based":
		expiry = _as_date(valid_to)
		if expiry is None or not (window_start <= expiry <= window_end):
			return []
		return [
			{
				"period_label": f"Renewal {expiry.isoformat()}",
				"period_start": expiry,
				"period_end": expiry,
				"due_date": expiry,
			}
		]

	span_start = window_start - timedelta(days=400)
	span_end = window_end
	if frequency == "Monthly":
		periods = []
		for year, month in _iter_months(span_start, span_end):
			period_start, period_end = _month_span(year, month)
			periods.append((_label_month(period_start), period_start, period_end))
	elif frequency == "Quarterly":
		periods = list(_quarters(basis, span_start, span_end))
	elif frequency == "Half-yearly":
		periods = list(_halves(basis, span_start, span_end))
	elif frequency == "Yearly":
		periods = list(_years(basis, span_start, span_end))
	else:
		return []

	rows = []
	seen = set()
	for label, period_start, period_end in periods:
		if label in seen:
			continue
		if effective_from and period_end < effective_from:
			continue
		if effective_to and period_start > effective_to:
			continue
		due = due_on(period_end, due_day, offset, overrides)
		if due < window_start or due > window_end:
			continue
		seen.add(label)
		rows.append(
			{
				"period_label": label,
				"period_start": period_start,
				"period_end": period_end,
				"due_date": due,
			}
		)
	return rows

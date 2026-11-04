"""Pure status, evidence, reminder, and escalation decisions."""

from datetime import date, datetime, timedelta

TERMINAL = {"Completed", "Not Applicable", "Waived"}
OPEN = {"Not Started", "In Progress", "Pending Review"}
OVERDUE_MARKER = -1
ESCALATION_MARKER = -2


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


def overdue_flags(status, due, today):
	today = _as_date(today)
	due = _as_date(due)
	if status in TERMINAL or due is None or today is None or today <= due:
		return False, 0
	return True, (today - due).days


def evidence_block(evidence_required, evidence_count, ack_no):
	if evidence_required and not int(evidence_count or 0) and not (ack_no or "").strip():
		return "Add evidence or an acknowledgement number before completing this activity."
	return None


def transition(status, action, has_reviewer):
	"""Return the next status, or (None, error)."""
	action = (action or "").strip()
	if action == "start":
		if status in TERMINAL:
			return None, "This activity is already closed."
		return "In Progress", None
	if action in ("submit", "complete"):
		if status in TERMINAL:
			return None, "This activity is already closed."
		if has_reviewer:
			return "Pending Review", None
		return "Completed", None
	if action == "approve":
		if status != "Pending Review":
			return None, "Only an activity pending review can be approved."
		return "Completed", None
	if action == "reject":
		if status != "Pending Review":
			return None, "Only an activity pending review can be sent back."
		return "In Progress", None
	if action == "not_applicable":
		return "Not Applicable", None
	if action == "waive":
		return "Waived", None
	return None, f"Unknown action: {action}"


def parse_offsets(raw):
	offsets = []
	for part in str(raw or "").split(","):
		part = part.strip()
		if not part:
			continue
		try:
			offsets.append(int(part))
		except ValueError:
			continue
	return offsets


def offsets_to_send(due, today, offsets, already_sent):
	due = _as_date(due)
	today = _as_date(today)
	if due is None or today is None or today > due:
		return []
	sent = set(already_sent or [])
	due_offsets = []
	for offset in offsets or []:
		if offset < 0 or offset in sent:
			continue
		if due - timedelta(days=offset) <= today:
			due_offsets.append(offset)
	return sorted(due_offsets, reverse=True)


def overdue_should_send(due, today, every_days, last_overdue_sent):
	due = _as_date(due)
	today = _as_date(today)
	last = _as_date(last_overdue_sent)
	if due is None or today is None or today <= due:
		return False
	every = int(every_days or 0)
	if every <= 0:
		return False
	if last is None:
		return True
	return (today - last).days >= every


def should_escalate(due, today, after_days, already):
	due = _as_date(due)
	today = _as_date(today)
	if due is None or today is None or today <= due or already:
		return False
	return (today - due).days >= int(after_days or 0)

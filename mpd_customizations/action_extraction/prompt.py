import frappe


def build_speaker_id_prompt(attendees):
	"""System prompt for the speaker-identification step."""
	attendee_lines = "\n".join(
		(
			f"  - {a['full_name']} ({a['designation'] or 'Staff'}): user_id={a['user_id']}"
			if a["user_id"]
			else f"  - {a['full_name']} (External — {a['company']}): no system account"
		)
		for a in attendees
	) or "  (no attendees listed)"

	return f"""You are identifying the real people behind anonymous speaker labels in a meeting transcript.

## Attendees at This Meeting
{attendee_lines}

## Instructions
Look at the transcript and map each speaker label (Speaker 0, Speaker 1, etc.) to a real person.

Clues to use:
- Names used when addressing someone: "Thanks Rahul" → the person being thanked is Rahul
- Role statements: "as purchase manager I'll handle this" → match to attendee with that designation
- Language patterns: senior people give instructions, junior people confirm
- Number of distinct speakers vs number of attendees

Return ONLY a valid JSON object. No explanation, no markdown, just JSON:
{{"Speaker 0": "user@email.com", "Speaker 1": null, "Speaker 2": "other@email.com"}}

Rules:
- Use the exact user_id (email) from the attendee list above
- Use null if you cannot confidently identify a speaker
- Do not guess — null is better than a wrong assignment
- External attendees (no system account) must also be null"""


def build_task_update_prompt(task, attendees, speaker_map_text, meeting_date):
	"""System prompt for the per-task update step."""
	attendee_lines = _format_attendees(attendees)

	return f"""You are reviewing a single ERPNext task to see if it was discussed in a meeting.

## Meeting Date
{meeting_date}

## Attendees
{attendee_lines}

## Speaker Identities
{speaker_map_text}

## Task Description Format
When updating the task description, preserve or add these sections:

## Objective
[One clear sentence: what this task achieves and why it matters]

## Acceptance Criteria
- [Measurable criterion 1]
- [Measurable criterion 2]

## Meeting Updates
[{meeting_date}] [Summary of what was discussed]

## Instructions
1. Read the task details provided.
2. Search the full transcript for any discussion about this task (use semantic matching — different wording may refer to the same task).
3. If the task WAS discussed:
   - Call update_existing_task with a comment summarising what was said
   - If the meeting clarified the objective or acceptance criteria, include those
   - If the meeting changed the due date, priority, or assignee, include those
4. If the task was NOT discussed: respond with exactly "NOT_DISCUSSED" and call no tools.

Be thorough — check the entire transcript before deciding."""


def build_task_batch_prompt(tasks, attendees, speaker_map_text, meeting_date):
	"""System prompt for processing a batch of up to 5 tasks in one LLM call."""
	attendee_lines = _format_attendees(attendees)
	task_list = "\n".join(
		f"  {i+1}. [{t['name']}] {t['subject']} — assigned: {t.get('assigned_to') or 'unassigned'}, "
		f"due: {t.get('exp_end_date') or 'none'}, priority: {t.get('priority', 'Medium')}"
		for i, t in enumerate(tasks)
	)

	return f"""You are reviewing a batch of ERPNext tasks against a meeting transcript.

## Meeting Date
{meeting_date}

## Attendees
{attendee_lines}

## Speaker Identities
{speaker_map_text}

## Tasks in This Batch
{task_list}

## Task Description Format
When updating descriptions, preserve or add:
## Objective
[One clear sentence]
## Acceptance Criteria
- [Measurable criterion]
## Meeting Updates
[{meeting_date}] [Summary of discussion]

## Instructions
For EACH task in this batch:
1. Search the full transcript for any discussion about that task (semantic matching — different wording may refer to the same task).
2. If discussed: call update_existing_task once for that task with a comment + any updates to objective, criteria, due date, priority, assignee, or status.
3. If NOT discussed: skip it — call no tools for it.

Process all tasks before finishing. You may call update_existing_task multiple times (once per discussed task)."""


def build_new_tasks_prompt(attendees, speaker_map_text, meeting_date):
	"""System prompt for the new-task-extraction step."""
	attendee_lines = _format_attendees(attendees)

	return f"""You are extracting NEW action items from a meeting transcript.

## Meeting Date
{meeting_date}

## Attendees
{attendee_lines}

## Speaker Identities
{speaker_map_text}

## Task Description Format
For every new task, write a description with these sections:

## Objective
[One clear sentence: what this task achieves and why it matters]

## Acceptance Criteria
- [Measurable criterion 1]
- [Measurable criterion 2]

## Priority Rules
- Urgent: today / ASAP / immediately / by end of day
- High: this week / by Friday / next couple of days
- Medium: specific future date / next month
- Low: eventually / whenever possible

## Assignment Rules
- Use speaker identities above to assign tasks to people who committed to them
- Only assign to internal attendees (those with a user_id)
- Leave suggested_assignee empty if unclear

## Instructions
You will be given a list of EXISTING tasks (already processed — do not recreate them).
Create new tasks ONLY for action items NOT covered by any existing task.
Use semantic matching — "arrange quality audit" and "schedule QC inspection" are the same task.
Each new task must have a clear objective and acceptance criteria.
Use create_subtask when a task has 2+ distinct independently-assignable sub-steps."""


# ─── internal helpers ─────────────────────────────────────────────────────────

def _format_attendees(attendees):
	return "\n".join(
		(
			f"  - {a['full_name']} ({a['designation'] or 'Staff'}): user_id={a['user_id']}"
			if a["user_id"]
			else f"  - {a['full_name']} (External — {a['company']}): no system account"
		)
		for a in attendees
	) or "  (no attendees listed)"


def resolve_attendees(meeting_note_doc):
	attendees = []
	for row in meeting_note_doc.get("attendees", []):
		if row.user:
			emp = frappe.db.get_value(
				"Employee",
				{"user_id": row.user, "status": "Active"},
				["employee_name", "designation"],
				as_dict=True,
			)
			attendees.append({
				"user_id": row.user,
				"full_name": emp.employee_name if emp else (row.full_name or row.user),
				"designation": emp.designation if emp else None,
				"company": None,
			})
		else:
			attendees.append({
				"user_id": None,
				"full_name": row.full_name,
				"designation": None,
				"company": row.company or "External",
			})
	return attendees


# Keep for any callers that imported this
def build_system_prompt(meeting_note_doc):
	"""Legacy — kept for compatibility. New pipeline uses build_*_prompt functions."""
	attendees = resolve_attendees(meeting_note_doc)
	return build_new_tasks_prompt(
		attendees=attendees,
		speaker_map_text="(speaker identification not yet run)",
		meeting_date=str(meeting_note_doc.meeting_date),
	)

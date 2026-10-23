TOOL_DEFINITIONS = [
	{
		"type": "function",
		"function": {
			"name": "update_existing_task",
			"description": (
				"Update an existing open task with discussion from this meeting. "
				"Always add a comment summarising what was said. "
				"Optionally update objective, acceptance criteria, due date, assignee, or priority."
			),
			"parameters": {
				"type": "object",
				"properties": {
					"task_name": {
						"type": "string",
						"description": "The ERPNext Task name (e.g. 'TASK-00042').",
					},
					"comment": {
						"type": "string",
						"description": "Summary of what was discussed about this task in the meeting.",
					},
					"new_priority": {
						"type": "string",
						"enum": ["Urgent", "High", "Medium", "Low"],
						"description": "Update priority only if the meeting changed urgency.",
					},
					"objective": {
						"type": "string",
						"description": (
							"One sentence stating what this task achieves and why. "
							"Set if the meeting clarified the task's goal."
						),
					},
					"acceptance_criteria": {
						"type": "string",
						"description": (
							"Bullet-point list (one per line, starting with -) of measurable conditions "
							"that define when this task is done. "
							"Set if the meeting defined or updated completion criteria."
						),
					},
					"new_due_date": {
						"type": "string",
						"description": "Updated due date in YYYY-MM-DD format if the meeting changed the deadline.",
					},
					"new_assignee": {
						"type": "string",
						"description": "User ID (email) if the meeting reassigned this task. Leave empty if unchanged.",
					},
					"new_status": {
						"type": "string",
						"enum": ["Completed", "Cancelled"],
						"description": (
							"Set ONLY if the meeting explicitly confirmed this task is done or cancelled. "
							"Do not set if there is any doubt."
						),
					},
				},
				"required": ["task_name", "comment"],
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "reopen_task",
			"description": (
				"Reopen a recently completed or cancelled task that the meeting indicated is not actually done "
				"or needs further work. Adds a comment explaining why it was reopened."
			),
			"parameters": {
				"type": "object",
				"properties": {
					"task_name": {
						"type": "string",
						"description": "The ERPNext Task name (e.g. 'TASK-00042').",
					},
					"comment": {
						"type": "string",
						"description": "Explanation of why this task is being reopened based on meeting discussion.",
					},
					"new_due_date": {
						"type": "string",
						"description": "New due date in YYYY-MM-DD format if discussed.",
					},
				},
				"required": ["task_name", "comment"],
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "create_pending_task",
			"description": (
				"Create a new task for an action item discussed in the meeting that is NOT already "
				"covered by an existing task. Include objective and acceptance criteria."
			),
			"parameters": {
				"type": "object",
				"properties": {
					"subject": {
						"type": "string",
						"description": "Task subject in 'Verb + Object' format. Concise and actionable.",
					},
					"project": {
						"type": "string",
						"description": "ERPNext Project name/ID.",
					},
					"description": {
						"type": "string",
						"description": "General context about the task.",
					},
					"objective": {
						"type": "string",
						"description": "One sentence: what this task achieves and why it matters.",
					},
					"acceptance_criteria": {
						"type": "string",
						"description": "Bullet-point list (- item per line) of measurable completion criteria.",
					},
					"suggested_assignee": {
						"type": "string",
						"description": "User ID (email) if clearly identified in transcript. Leave empty if unclear.",
					},
					"priority": {
						"type": "string",
						"enum": ["Urgent", "High", "Medium", "Low"],
						"description": "today/ASAP → Urgent; this week → High; otherwise → Medium.",
					},
					"exp_end_date": {
						"type": "string",
						"description": "Due date YYYY-MM-DD if mentioned.",
					},
				},
				"required": ["subject", "project", "description", "priority"],
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "create_subtask",
			"description": (
				"Create a subtask under an existing parent task. "
				"Use only when a task has clear, distinct sub-steps. "
				"Always create the parent task first via create_pending_task."
			),
			"parameters": {
				"type": "object",
				"properties": {
					"subject": {
						"type": "string",
						"description": "Subtask subject in 'Verb + Object' format.",
					},
					"parent_task": {
						"type": "string",
						"description": "ERPNext Task name of the parent task.",
					},
					"project": {
						"type": "string",
						"description": "ERPNext Project name/ID.",
					},
					"description": {
						"type": "string",
						"description": "What this subtask requires.",
					},
					"suggested_assignee": {
						"type": "string",
						"description": "User ID if clearly implied. Leave empty if uncertain.",
					},
					"priority": {
						"type": "string",
						"enum": ["Urgent", "High", "Medium", "Low"],
					},
					"exp_end_date": {
						"type": "string",
						"description": "Due date YYYY-MM-DD if mentioned.",
					},
				},
				"required": ["subject", "parent_task", "project"],
			},
		},
	},
]

# Subsets used per pipeline step
TASK_UPDATE_TOOLS = [t for t in TOOL_DEFINITIONS if t["function"]["name"] == "update_existing_task"]
REOPEN_TOOLS      = [t for t in TOOL_DEFINITIONS if t["function"]["name"] == "reopen_task"]
NEW_TASK_TOOLS    = [t for t in TOOL_DEFINITIONS if t["function"]["name"] in ("create_pending_task", "create_subtask")]

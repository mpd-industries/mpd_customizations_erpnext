"""Seed AI Task Config rows for the Drive inbox. Skips keys that already exist."""

import frappe

from mpd_customizations.drive.ai.prompts import INBOX_CLASSIFY_PROMPT

LLM_PROVIDER = "OpenRouter"
MODEL = "openrouter/google/gemini-3.1-flash-lite"

CONFIGS = [
	{
		"task_key": "drive_inbox_classify",
		"task_label": "Drive Inbox Classification",
		"description": "Names a Drive upload and chooses the subject folder it belongs in.",
		"system_prompt": INBOX_CLASSIFY_PROMPT,
	},
]


def execute():
	if not frappe.db.exists("DocType", "AI Task Config"):
		return
	if not frappe.db.exists("LLM Provider", LLM_PROVIDER):
		frappe.logger("drive").info("seed_drive_ai_task_configs: OpenRouter provider missing, skipping")
		return
	for cfg in CONFIGS:
		if frappe.db.exists("AI Task Config", {"task_key": cfg["task_key"]}):
			continue
		frappe.get_doc(
			{
				"doctype": "AI Task Config",
				"name": cfg["task_key"],
				"task_key": cfg["task_key"],
				"task_label": cfg["task_label"],
				"description": cfg["description"],
				"llm_provider": LLM_PROVIDER,
				"model": MODEL,
				"temperature": 0.1,
				"max_tokens": 4000,
				"system_prompt": cfg["system_prompt"],
				"is_active": 1,
			}
		).insert(ignore_permissions=True)
	frappe.db.commit()

import os

import frappe

from mpd_customizations.setup.item_classification_prompt import ITEM_CLASSIFICATION_SYSTEM_PROMPT


def seed_llm_fixtures():
    """OpenRouter provider + item_classification + meeting_note_extraction tasks. Idempotent."""
    if not frappe.db.exists("DocType", "LLM Provider"):
        return
    _seed_openrouter_provider()
    _seed_item_classification_config()
    _seed_meeting_note_extraction_config()
    frappe.db.commit()
    print("Seeded LLM fixtures (OpenRouter + item_classification + meeting_note_extraction)")


def sync_item_classification_system_prompt_from_code():
    """Overwrite AI Task Config system_prompt from ITEM_CLASSIFICATION_SYSTEM_PROMPT."""
    if not frappe.db.exists("AI Task Config", "item_classification"):
        return
    doc = frappe.get_doc("AI Task Config", "item_classification")
    doc.system_prompt = ITEM_CLASSIFICATION_SYSTEM_PROMPT
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    print("Synced item_classification system prompt from code (MPD_SYNC_ITEM_AI_PROMPT=1)")


def _seed_openrouter_provider():
    if frappe.db.exists("LLM Provider", "OpenRouter"):
        return
    api_key = os.environ.get("OPENROUTER_API_KEY", "set-api-key-in-llm-provider")
    doc = frappe.get_doc({
        "doctype": "LLM Provider",
        "provider_name": "OpenRouter",
        "api_base": "https://openrouter.ai/api/v1",
        "api_key": api_key,
        "is_active": 1,
        "notes": "API key can be overridden via OPENROUTER_API_KEY env at install time.",
    })
    doc.insert(ignore_permissions=True)


def _seed_item_classification_config():
    if frappe.db.exists("AI Task Config", "item_classification"):
        return
    doc = frappe.get_doc({
        "doctype": "AI Task Config",
        "name": "item_classification",
        "task_key": "item_classification",
        "task_label": "Item Classification",
        "llm_provider": "OpenRouter",
        "model": "openrouter/google/gemini-3.1-flash-lite-preview",
        "temperature": 0.1,
        "max_tokens": 2000,
        "system_prompt": ITEM_CLASSIFICATION_SYSTEM_PROMPT,
        "is_active": 1,
        "parameters": [
            {"parameter_key": "confidence_threshold", "parameter_value": "0.85"},
            {"parameter_key": "max_candidates", "parameter_value": "5"},
        ],
    })
    doc.insert(ignore_permissions=True)


def _seed_meeting_note_extraction_config():
    """
    Seeds an AI Task Config for meeting note extraction.

    Uses the existing OpenRouter provider. Model is read from frappe.conf
    (openrouter_model) if set, otherwise defaults to claude-sonnet-4-6.
    Skips silently if OpenRouter provider doesn't exist yet.
    """
    if frappe.db.exists("AI Task Config", "meeting_note_extraction"):
        return
    if not frappe.db.exists("LLM Provider", "OpenRouter"):
        return

    model = (
        frappe.conf.get("openrouter_model")
        or "openrouter/anthropic/claude-sonnet-4-6"
    )

    doc = frappe.get_doc({
        "doctype": "AI Task Config",
        "name": "meeting_note_extraction",
        "task_key": "meeting_note_extraction",
        "task_label": "Meeting Note Action Extraction",
        "description": (
            "Analyses meeting transcripts and creates/updates project tasks. "
            "Change model or provider here without any code changes."
        ),
        "llm_provider": "OpenRouter",
        "model": model,
        "temperature": 0.2,
        "max_tokens": 4000,
        "is_active": 1,
    })
    doc.insert(ignore_permissions=True)

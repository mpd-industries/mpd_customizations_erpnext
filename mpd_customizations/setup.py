import frappe

DEFAULT_PROVIDERS = [
    {
        "provider_name":  "Anthropic",
        "provider_key":   "anthropic",
        "enabled":        1,
        "fallback_order": 1,
    },
    {
        "provider_name":  "OpenAI",
        "provider_key":   "openai",
        "enabled":        0,
        "fallback_order": 2,
    },
    {
        "provider_name":  "Google",
        "provider_key":   "google",
        "enabled":        0,
        "fallback_order": 3,
    },
    {
        "provider_name":  "OpenRouter",
        "provider_key":   "openrouter",
        "api_base_url":   "https://openrouter.ai/api/v1",
        "enabled":        0,
        "fallback_order": 4,
    },
]

DEFAULT_TASKS = [
    {
        "task_name":            "Item Master Review",
        "task_key":             "item_review",
        "model_string":         "anthropic/claude-sonnet-4-6",
        "temperature":          0.1,
        "max_tokens":           1500,
        "confidence_threshold": 75,
        "enabled":              1,
    },
    {
        "task_name":            "Customer Master Review",
        "task_key":             "customer_review",
        "model_string":         "anthropic/claude-sonnet-4-6",
        "temperature":          0.1,
        "max_tokens":           1000,
        "confidence_threshold": 80,
        "enabled":              1,
    },
    {
        "task_name":            "Supplier Master Review",
        "task_key":             "supplier_review",
        "model_string":         "anthropic/claude-sonnet-4-6",
        "temperature":          0.1,
        "max_tokens":           1000,
        "confidence_threshold": 80,
        "enabled":              1,
    },
]


def after_install():
    from frappe.utils.fixtures import sync_fixtures
    sync_fixtures("mpd_customizations")
    _seed_providers()
    _seed_tasks()
    frappe.db.commit()


def after_migrate():
    from frappe.utils.fixtures import sync_fixtures
    sync_fixtures("mpd_customizations")
    _seed_providers()
    frappe.db.commit()


def _seed_providers():
    for p in DEFAULT_PROVIDERS:
        if not frappe.db.exists(
            "LLM Provider", p["provider_name"]
        ):
            frappe.get_doc({
                "doctype": "LLM Provider", **p
            }).insert(ignore_permissions=True)


def _seed_tasks():
    provider = frappe.db.get_value(
        "LLM Provider",
        {"enabled": 1, "fallback_order": 1},
        "name",
    )
    for t in DEFAULT_TASKS:
        if not frappe.db.get_value(
            "LLM Task",
            {"task_key": t["task_key"]},
            "name",
        ):
            frappe.get_doc({
                "doctype":        "LLM Task",
                **t,
                "provider":       provider,
                "system_prompt":  "",
                "prompt_version": 1,
            }).insert(ignore_permissions=True)

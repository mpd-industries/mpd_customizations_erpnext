import frappe


def get_task_config(task_key):
    """
    Fetch AI Task Config by task_key.
    Returns (config_doc, params_dict).
    params_dict maps parameter_key -> parameter_value (all strings).
    Cast to float/int in the caller as needed.

    Raises a clean error if the task is not configured or not active.
    """
    results = frappe.get_all(
        "AI Task Config",
        filters={"task_key": task_key, "is_active": 1},
        fields=["name"],
        limit=1,
    )
    if not results:
        frappe.throw(
            f"No active AI Task Config found for task key '{task_key}'. "
            f"Please create one in AI Task Config."
        )

    config = frappe.get_doc("AI Task Config", results[0].name)
    params = {row.parameter_key: row.parameter_value for row in config.parameters}
    return config, params
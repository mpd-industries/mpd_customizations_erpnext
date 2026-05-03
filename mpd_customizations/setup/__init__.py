import os

import frappe

from mpd_customizations.setup.item_category_codes import seed_item_category_codes
from mpd_customizations.setup.llm_fixtures import (
    seed_llm_fixtures,
    sync_item_classification_system_prompt_from_code,
    sync_oth_reclassification_config,
)


def after_install():
    seed_item_category_codes()
    seed_llm_fixtures()
    backfill_item_labels()


def after_migrate():
    """Ensure LLM fixtures exist on upgraded sites (idempotent)."""
    seed_llm_fixtures()
    sync_oth_reclassification_config()
    backfill_item_labels()
    if os.environ.get("MPD_SYNC_ITEM_AI_PROMPT") == "1":
        sync_item_classification_system_prompt_from_code()


def backfill_item_labels():
    """
    Populate custom_item_label for every Item that doesn't have one yet,
    and refresh any item where tally_name/alias may have changed since the
    field was added. Uses direct DB writes (no full save, no hook re-entry).
    """
    from mpd_customizations.mpd_base.item_ai.item_hooks import compute_item_label

    if not frappe.db.has_column("Item", "custom_item_label"):
        return

    items = frappe.get_all(
        "Item",
        fields=["name", "item_name", "custom_tally_name", "custom_tally_alias", "custom_item_label"],
    )

    updated = 0
    for item in items:
        label = compute_item_label(
            item.item_name,
            item.custom_tally_name,
            item.custom_tally_alias,
        )
        if label != (item.custom_item_label or ""):
            frappe.db.set_value("Item", item.name, "custom_item_label", label, update_modified=False)
            updated += 1

    if updated:
        frappe.db.commit()
        print(f"Backfilled custom_item_label for {updated} item(s).")

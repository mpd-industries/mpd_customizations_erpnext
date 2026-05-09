import os
import re

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
    backfill_item_solids()
    _migrate_pending_rate_items()
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


def backfill_item_solids():
    """
    Populate custom_solids_content_pct for items whose name contains a
    percentage value (e.g. 'Alkyl Phenolic Resin PHE5164, 99%' → 99.0).
    Only fills items where the field is currently NULL or 0 — never
    overwrites a value that was set manually.
    """
    if not frappe.db.has_column("Item", "custom_solids_content_pct"):
        return

    items = frappe.get_all(
        "Item",
        fields=["name", "item_name", "custom_solids_content_pct"],
    )

    updated = 0
    for item in items:
        if item.custom_solids_content_pct:
            continue
        matches = re.findall(r"(\d+(?:\.\d+)?)\s*%", item.item_name or "")
        if not matches:
            continue
        # take the last percentage in the name — the solids spec is always
        # the trailing descriptor (e.g. "Resin XYZ, 99%")
        pct = float(matches[-1])
        if pct <= 0 or pct > 100:
            continue
        frappe.db.set_value("Item", item.name, "custom_solids_content_pct", pct, update_modified=False)
        updated += 1

    if updated:
        frappe.db.commit()
        print(f"Backfilled custom_solids_content_pct for {updated} item(s).")


def _migrate_pending_rate_items():
    """One-time: clear the old Pending Rate Item table (replaced by Material Rate drafts)."""
    if not frappe.db.table_exists("tabPending Rate Item"):
        return
    count = frappe.db.count("Pending Rate Item")
    if count:
        frappe.db.delete("Pending Rate Item", {})
        frappe.db.commit()
        print(f"Cleared {count} legacy Pending Rate Item record(s). Re-run 'Create Pending Rates' to regenerate.")

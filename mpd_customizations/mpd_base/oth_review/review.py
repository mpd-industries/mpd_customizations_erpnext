import frappe
from frappe.utils import now_datetime


# ─── Load ─────────────────────────────────────────────────────────────────────

@frappe.whitelist()
def load_oth_items(doc_name):
    """
    Queries all active Items whose item_code starts with 'OTH-' and writes
    them into the items child table of the OTH Reclassification document.
    Replaces any previously loaded rows.
    """
    doc = frappe.get_doc("OTH Reclassification", doc_name)

    oth_items = frappe.get_all(
        "Item",
        filters={"item_code": ["like", "OTH-%"], "disabled": 0},
        fields=[
            "item_code", "item_name", "item_group",
            "stock_uom", "gst_hsn_code",
            "custom_tally_name", "custom_tally_alias",
        ],
        order_by="item_code",
    )

    doc.set("items", [])
    for item in oth_items:
        doc.append("items", {
            "item_code":   item.item_code,
            "item_name":   item.item_name,
            "item_group":  item.item_group,
            "uom":         item.stock_uom,
            "hsn":         item.gst_hsn_code or "",
            "tally_name":  item.custom_tally_name or "",
            "tally_alias": item.custom_tally_alias or "",
        })

    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return {"loaded": len(oth_items)}


# ─── Enqueue ──────────────────────────────────────────────────────────────────

@frappe.whitelist()
def enqueue_oth_review(doc_name):
    """
    Sets status to Analyzing and queues the background LLM job.
    Called by the Analyze with AI button.
    """
    frappe.db.set_value("OTH Reclassification", doc_name, "status", "Analyzing")
    frappe.db.commit()

    frappe.enqueue(
        "mpd_customizations.mpd_base.oth_review.review.run_oth_review",
        doc_name=doc_name,
        queue="long",
        timeout=600,
    )
    return {"status": "queued"}


# ─── Background job ───────────────────────────────────────────────────────────

BATCH_SIZE = 40  # items per LLM call — keeps response well under token limits


def run_oth_review(doc_name):
    """
    Main background job. Splits items into batches of BATCH_SIZE, calls the LLM
    once per batch, then merges all results and writes them to the doc.
    """
    try:
        doc = frappe.get_doc("OTH Reclassification", doc_name)

        if not doc.items:
            frappe.db.set_value("OTH Reclassification", doc_name, "status", "Draft")
            frappe.db.commit()
            frappe.log_error(
                title=f"OTH Review {doc_name}: no items loaded",
                message="Load OTH Items before running analysis.",
            )
            return

        from mpd_customizations.utils import get_task_config
        from mpd_customizations.mpd_base.item_ai.llm_call import call_llm

        config, _params = get_task_config("oth_reclassification")

        # Build shared context (same for every batch)
        context = _build_context()

        # Split items into batches
        all_items = list(doc.items)
        batches = [all_items[i:i + BATCH_SIZE] for i in range(0, len(all_items), BATCH_SIZE)]

        # Accumulated results across all batches
        merged = {
            "summary":       [],
            "items":         [],
            "new_prefixes":  [],
            "new_item_groups": [],
        }

        for batch_num, batch in enumerate(batches, start=1):
            user_prompt = _build_batch_prompt(context, batch, batch_num, len(batches))
            result = call_llm(
                config=config,
                system_prompt=config.system_prompt,
                user_prompt=user_prompt,
                reference_doctype="OTH Reclassification",
                reference_name=f"{doc_name} batch {batch_num}/{len(batches)}",
            )
            if result.get("summary"):
                merged["summary"].append(f"Batch {batch_num}: {result['summary']}")
            merged["items"].extend(result.get("items") or [])
            # Deduplicate new prefixes and item groups by name
            for p in (result.get("new_prefixes") or []):
                if not any(x["prefix"] == p.get("prefix") for x in merged["new_prefixes"]):
                    merged["new_prefixes"].append(p)
            for g in (result.get("new_item_groups") or []):
                if not any(x["item_group_name"] == g.get("item_group_name") for x in merged["new_item_groups"]):
                    merged["new_item_groups"].append(g)

        merged["summary"] = "\n\n".join(merged["summary"])
        _apply_result(doc, merged)

    except Exception:
        frappe.log_error(
            title=f"OTH Review failed for {doc_name}",
            message=frappe.get_traceback(),
        )
        frappe.db.set_value("OTH Reclassification", doc_name, "status", "Draft")
        frappe.db.commit()


def _build_context():
    """
    Fetches the shared classification context (Item Category Codes + Item Groups).
    Called once before batching to avoid repeated DB queries.
    Returns a dict with pre-formatted text blocks.
    """
    categories = frappe.get_all(
        "Item Category Code",
        filters={"is_active": 1},
        fields=[
            "prefix", "full_name", "domain", "description",
            "example_code", "example_item_name",
            "llm_guidance_notes",
        ],
    )
    cat_lines = []
    for c in categories:
        line = f"- {c.prefix}: {c.full_name} [{c.domain}]"
        if c.description:
            line += f"\n  What belongs here: {c.description}"
        if c.example_code:
            line += f"\n  Example: {c.example_code} — {c.example_item_name}"
        if c.llm_guidance_notes:
            line += f"\n  Guidance: {c.llm_guidance_notes}"
        cat_lines.append(line)

    item_groups = frappe.get_all(
        "Item Group",
        fields=["name"],
        order_by="name",
    )

    return {
        "cat_block":    "\n".join(cat_lines),
        "groups_block": "\n".join(f"- {g.name}" for g in item_groups),
    }


def _build_batch_prompt(context, batch, batch_num, total_batches):
    """
    Builds the user-turn prompt for a single batch of items.
    """
    item_lines = []
    for row in batch:
        parts = [f'"item_code": "{row.item_code}"']
        parts.append(f'"item_name": "{row.item_name}"')
        parts.append(f'"item_group": "{row.item_group}"')
        parts.append(f'"uom": "{row.uom}"')
        if row.hsn:
            parts.append(f'"hsn": "{row.hsn}"')
        if row.tally_name:
            parts.append(f'"tally_name": "{row.tally_name}"')
        if row.tally_alias:
            parts.append(f'"tally_alias": "{row.tally_alias}"')
        item_lines.append("{" + ", ".join(parts) + "}")

    prompt = f"""
--- ACTIVE ITEM CATEGORY CODES ---
{context["cat_block"]}

--- VALID ITEM GROUPS (assign suggested_item_group to exactly one of these, or propose a new one in new_item_groups) ---
{context["groups_block"]}

--- OTH ITEMS TO RECLASSIFY (batch {batch_num} of {total_batches}) ---
Items in this batch: {len(batch)}

{chr(10).join(item_lines)}
"""
    return prompt


def _apply_result(doc, result):
    """
    Writes LLM output back to the OTH Reclassification doc.
    """
    doc.ai_summary = result.get("summary") or ""
    doc.analyzed_on = now_datetime()

    # Item suggestions
    doc.set("suggestions", [])
    for item_result in (result.get("items") or []):
        item_code = item_result.get("item_code", "")
        # Lookup current item name and group
        current_name = frappe.db.get_value("Item", item_code, "item_name") or ""
        current_group = frappe.db.get_value("Item", item_code, "item_group") or ""

        suggested_group = item_result.get("suggested_item_group", "")
        # Validate the group exists (could be a new one from new_item_groups — allow it)
        if suggested_group and not frappe.db.exists("Item Group", suggested_group):
            # It's a proposed new group — store the name as text, don't validate link
            suggested_group_link = None
            notes = (item_result.get("notes") or "") + f" [New group: {suggested_group}]"
        else:
            suggested_group_link = suggested_group
            notes = item_result.get("notes") or None

        doc.append("suggestions", {
            "item_code":            item_code,
            "current_item_name":    current_name,
            "current_item_group":   current_group,
            "suggested_prefix":     item_result.get("suggested_prefix", ""),
            "suggested_item_group": suggested_group_link,
            "suggested_item_name":  item_result.get("suggested_item_name", ""),
            "confidence":           float(item_result.get("confidence", 0)),
            "action":               "Apply",
            "notes":                notes,
        })

    # New prefix suggestions
    doc.set("new_prefixes", [])
    for p in (result.get("new_prefixes") or []):
        doc.append("new_prefixes", {
            "prefix":            p.get("prefix", ""),
            "full_name":         p.get("full_name", ""),
            "domain":            p.get("domain", "Other"),
            "description":       p.get("description", ""),
            "example_item_name": p.get("example_item_name", ""),
            "action":            "Create",
        })

    # New item group suggestions
    doc.set("new_item_groups", [])
    for g in (result.get("new_item_groups") or []):
        parent = g.get("parent_item_group", "")
        if not frappe.db.exists("Item Group", parent):
            parent = ""
        doc.append("new_item_groups", {
            "item_group_name":   g.get("item_group_name", ""),
            "parent_item_group": parent,
            "action":            "Create",
        })

    doc.status = "Reviewed"
    doc.save(ignore_permissions=True)
    frappe.db.commit()


# ─── Apply suggestions ────────────────────────────────────────────────────────

@frappe.whitelist()
def apply_suggestions(doc_name):
    """
    Processes all action rows in one pass:
      - new_item_groups where action=Create  → inserts Item Group
      - new_prefixes where action=Create     → inserts Item Category Code
      - suggestions where action=Apply       → renames Item + updates item_group/item_name
    New groups are created first so item suggestions can reference them.
    Returns a summary dict for the client to display.
    """
    doc = frappe.get_doc("OTH Reclassification", doc_name)

    groups_created = _create_item_groups(doc)
    prefixes_created = _create_prefixes(doc)
    items_renamed, rename_errors = _rename_items(doc)

    doc.status = "Applied"
    doc.save(ignore_permissions=True)
    frappe.db.commit()

    return {
        "groups_created":  groups_created,
        "prefixes_created": prefixes_created,
        "items_renamed":   items_renamed,
        "rename_errors":   rename_errors,
    }


def _create_item_groups(doc):
    created = 0
    for row in doc.new_item_groups:
        if row.action != "Create":
            continue
        if not row.item_group_name:
            continue
        if frappe.db.exists("Item Group", row.item_group_name):
            continue
        parent = row.parent_item_group or "All Item Groups"
        try:
            ig = frappe.get_doc({
                "doctype":          "Item Group",
                "item_group_name":  row.item_group_name,
                "parent_item_group": parent,
                "is_group":         0,
            })
            ig.insert(ignore_permissions=True)
            created += 1
        except Exception:
            frappe.log_error(
                title=f"OTH Review: failed to create Item Group '{row.item_group_name}'",
                message=frappe.get_traceback(),
            )
    frappe.db.commit()
    return created


def _create_prefixes(doc):
    created = 0
    for row in doc.new_prefixes:
        if row.action != "Create":
            continue
        if not row.prefix:
            continue
        if frappe.db.exists("Item Category Code", row.prefix):
            continue
        try:
            icc = frappe.get_doc({
                "doctype":           "Item Category Code",
                "prefix":            row.prefix,
                "full_name":         row.full_name or row.prefix,
                "domain":            row.domain or "Other",
                "description":       row.description or "",
                "example_item_name": row.example_item_name or "",
                "is_active":         1,
            })
            icc.insert(ignore_permissions=True)
            created += 1
        except Exception:
            frappe.log_error(
                title=f"OTH Review: failed to create Item Category Code '{row.prefix}'",
                message=frappe.get_traceback(),
            )
    frappe.db.commit()
    return created


def _rename_items(doc):
    renamed = 0
    errors = []

    for row in doc.suggestions:
        if row.action != "Apply":
            continue
        if not row.item_code or not row.suggested_prefix:
            continue

        old_code = row.item_code
        new_prefix = row.suggested_prefix.upper().strip()

        # Build sequential new code: PREFIX-XXXXX
        existing_count = frappe.db.count("Item", {"item_code": ["like", f"{new_prefix}-%"]})
        new_code = f"{new_prefix}-{str(existing_count + 1).zfill(5)}"
        # Avoid collision
        while frappe.db.exists("Item", new_code):
            existing_count += 1
            new_code = f"{new_prefix}-{str(existing_count + 1).zfill(5)}"

        try:
            # Rename cascades to all linked documents
            frappe.rename_doc("Item", old_code, new_code)

            # Update item_name and item_group on the renamed item
            updates = {}
            if row.suggested_item_name:
                updates["item_name"] = row.suggested_item_name
            if row.suggested_item_group and frappe.db.exists("Item Group", row.suggested_item_group):
                updates["item_group"] = row.suggested_item_group
            if updates:
                frappe.db.set_value("Item", new_code, updates)

            renamed += 1
        except Exception:
            msg = frappe.get_traceback()
            frappe.log_error(
                title=f"OTH Review: failed to rename '{old_code}' → '{new_code}'",
                message=msg,
            )
            errors.append(f"{old_code}: {msg[:200]}")

    frappe.db.commit()
    return renamed, errors

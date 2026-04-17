import json
import frappe
from frappe.utils import now_datetime


# ─── Enqueue ──────────────────────────────────────────────────────────────────

@frappe.whitelist()
def enqueue_item_ai_review(request_name):
    """
    Called by the Generate AI Suggestion button.
    Sets status to Pending AI Review and queues the background job.
    """
    frappe.db.set_value(
        "Item Request", request_name,
        "status", "Pending AI Review"
    )
    frappe.db.commit()

    frappe.enqueue(
        "mpd_customizations.mpd_base.item_ai.review.run_item_review",
        request_name=request_name,
        queue="default",
        timeout=180,
    )
    return {"status": "queued"}


# ─── Background job ───────────────────────────────────────────────────────────

def run_item_review(request_name):
    """
    Main background job. Builds prompt, calls LLM, applies result.
    """
    try:
        doc = frappe.get_doc("Item Request", request_name)

        # Get top 5 candidates from similarity search for LLM context
        from mpd_customizations.mpd_base.item_ai.dedup import check_item_duplicates
        top_candidates = check_item_duplicates(
            description=doc.requester_description,
            tally_name=doc.tally_name,
            tally_alias=doc.tally_alias,
            legacy_material_code=doc.legacy_material_code,
        )

        # Build prompt
        user_prompt = build_prompt(doc, top_candidates)

        # Multimodal only when a file is attached — otherwise plain text to the LLM
        if (doc.attach_documents or "").strip():
            file_data, file_mime = _read_attached_file(doc)
        else:
            file_data, file_mime = None, None

        # Get system prompt from AI Task Config
        from mpd_customizations.utils import get_task_config
        config, params = get_task_config("item_classification")

        # Call LLM
        from mpd_customizations.mpd_base.item_ai.llm_call import call_llm
        result = call_llm(
            config=config,
            system_prompt=config.system_prompt,
            user_prompt=user_prompt,
            reference_doctype="Item Request",
            reference_name=request_name,
            attached_file_data=file_data,
            attached_mime=file_mime,
        )

        # Apply result to doc
        apply_result(doc, result, config, params)

    except Exception:
        frappe.log_error(
            title=f"Item AI Review failed for {request_name}",
            message=frappe.get_traceback(),
        )
        frappe.db.set_value(
            "Item Request", request_name,
            "status", "Dedup Confirmed",
        )
        frappe.db.commit()


# ─── Prompt builder ───────────────────────────────────────────────────────────

def build_prompt(doc, top_candidates):
    """
    Builds the user-turn prompt with all context the LLM needs.
    Fetches live data from ERPNext on every call so it is always current.
    """

    # 1. Active Item Category Codes
    categories = frappe.get_all(
        "Item Category Code",
        filters={"is_active": 1},
        fields=[
            "prefix", "full_name", "domain", "description",
            "example_code", "example_item_name",
            "requires_solids_suffix", "has_sub_category",
            "sub_category_options", "llm_guidance_notes",
        ],
    )

    # 2. Leaf Item Groups only — is_group = 0 prevents LLM picking a parent node
    item_groups = frappe.get_all(
        "Item Group",
        filters={"is_group": 0},
        fields=["name"],
        order_by="name",
    )

    # 3. Asset Categories (only if fixed asset)
    asset_categories = []
    if doc.is_fixed_asset:
        asset_categories = frappe.get_all("Asset Category", fields=["name"])

    # Build category lines
    cat_lines = []
    for c in categories:
        line = f"- {c.prefix}: {c.full_name}"
        if c.description:
            line += f"\n  What belongs here: {c.description}"
        if c.example_code:
            line += f"\n  Example: {c.example_code} — {c.example_item_name}"
        if c.requires_solids_suffix:
            line += f"\n  NOTE: Requires solids % suffix e.g. -99, -80, -70"
        if c.has_sub_category:
            line += f"\n  Sub-categories: {c.sub_category_options}"
        if c.llm_guidance_notes:
            line += f"\n  Guidance: {c.llm_guidance_notes}"
        cat_lines.append(line)

    # Build candidates section
    if top_candidates:
        candidate_lines = []
        for c in top_candidates:
            line = f"- {c['name']}: {c['item_name']} [{c.get('item_group', '')}]"
            extras = []
            if c.get("tally_name"):           extras.append(f"tally:{c['tally_name']}")
            if c.get("tally_alias"):          extras.append(f"alias:{c['tally_alias']}")
            if c.get("legacy_material_code"): extras.append(f"legacy:{c['legacy_material_code']}")
            if c.get("gst_hsn_code"):         extras.append(f"hsn:{c['gst_hsn_code']}")
            if extras:
                line += f" ({', '.join(extras)})"
            candidate_lines.append(line)
        candidates_block = (
            "--- MOST SIMILAR EXISTING ITEMS ---\n"
            "The requester acknowledged these exist but believes their item is different.\n"
            "Evaluate whether you agree — chemicals often have multiple trade names But do allow same items with different packing sizes.\n\n"
            + "\n".join(candidate_lines)
        )
    else:
        candidates_block = (
            "--- MOST SIMILAR EXISTING ITEMS ---\n"
            "None found by similarity search."
        )

    # Asset section
    asset_block = ""
    if asset_categories:
        asset_block = (
            "\n--- ASSET CATEGORIES ---\n"
            + "\n".join(f"- {a.name}" for a in asset_categories)
        )

    uom_rows = frappe.get_all(
        "UOM",
        fields=["name"],
        order_by="name",
        limit_page_length=200,
    )
    uom_block = "\n".join(f"- {u.name}" for u in uom_rows)

    prompt = f"""
ITEM REQUEST:
  Description:           {doc.requester_description}
  Is Fixed Asset:        {"Yes" if doc.is_fixed_asset else "No"}
  Is Stock Item:         {"Yes" if doc.is_stock_item else "No"}
  HSN Code:              {doc.gst_hsn_code or "Not provided"}
  Stock UOM (requester): {doc.stock_uom or "Not provided"}
  Tally Name:            {doc.tally_name or "None"}
  Tally Alias:           {doc.tally_alias or "None"}
  Legacy Material Code:  {doc.legacy_material_code or "None"}

{candidates_block}

--- ACTIVE ITEM CATEGORY CODES ---
{chr(10).join(cat_lines)}

--- VALID ITEM GROUPS (leaf nodes only — pick exactly one, exact string match) ---
{chr(10).join(f"- {g.name}" for g in item_groups)}
{asset_block}

--- VALID UOM NAMES ---
Pick suggested_stock_uom from this list only (exact name match).
{uom_block}
"""
    return prompt


# ─── Apply result ─────────────────────────────────────────────────────────────

def apply_result(doc, result, config, params):
    """
    Writes LLM output to the Item Request doc.
    Freezes the snapshot.
    Decides auto-approval vs MA review.
    """
    doc.ai_item_name_suggestion      = result.get("item_name")
    doc.ai_prefix_suggestion         = result.get("prefix")
    doc.ai_sub_category_suggestion   = result.get("sub_category")
    doc.ai_item_group_suggestion     = result.get("item_group")
    doc.ai_asset_category_suggestion = result.get("asset_category")
    doc.ai_solids_suffix_suggestion  = result.get("solids_suffix")
    suggested_hsn = (result.get("suggested_hsn_code") or "").strip()
    doc.ai_hsn_suggestion = suggested_hsn or None
    doc.ai_hsn_note = (result.get("hsn_note") or "").strip() or None

    user_hsn = (doc.gst_hsn_code or "").strip()
    if not user_hsn and suggested_hsn:
        doc.gst_hsn_code = suggested_hsn
    # If user_hsn was set but differs from AI, we keep the requester's gst_hsn_code;
    # ai_hsn_suggestion + ai_hsn_note surface the AI correction.

    raw_uom = (result.get("suggested_stock_uom") or "").strip()
    if raw_uom and frappe.db.exists("UOM", raw_uom):
        doc.ai_uom_suggestion = raw_uom
    else:
        doc.ai_uom_suggestion = None
        if raw_uom:
            frappe.log_error(
                title="Invalid AI suggested_stock_uom",
                message=f"Value {raw_uom!r} is not a UOM name. Item Request: {doc.name}",
            )

    user_stock_uom = (doc.stock_uom or "").strip()
    if not user_stock_uom and doc.ai_uom_suggestion:
        doc.stock_uom = doc.ai_uom_suggestion

    doc.ai_review_brief              = result.get("review_brief")
    doc.ai_confidence_score          = float(result.get("confidence_score", 0))
    doc.ai_duplicate_warning         = result.get("duplicate_warning")
    doc.ai_reviewed_on               = now_datetime()
    doc.ai_model_used                = config.model
    doc.ai_suggested_new_prefix      = result.get("suggested_new_prefix")
    doc.ai_suggested_new_prefix_name = result.get("suggested_new_prefix_name")
    doc.ai_suggested_new_item_group  = result.get("suggested_new_item_group")

    # Freeze snapshot — never modified after this point
    snapshot = {
        "item_name":          result.get("item_name"),
        "prefix":             result.get("prefix"),
        "sub_category":       result.get("sub_category"),
        "item_group":         result.get("item_group"),
        "asset_category":     result.get("asset_category"),
        "solids_suffix":      result.get("solids_suffix"),
        "suggested_hsn_code":   result.get("suggested_hsn_code"),
        "hsn_note":             result.get("hsn_note"),
        "suggested_stock_uom":  result.get("suggested_stock_uom"),
    }
    doc.ai_snapshot = json.dumps(snapshot)

    # Decide approval path — order matters: duplicate > OTH > normal
    threshold     = float(params.get("confidence_threshold", 0.85))
    has_duplicate = bool(result.get("duplicate_warning"))
    is_oth        = result.get("prefix") == "OTH"
    high_conf     = doc.ai_confidence_score >= threshold

    if has_duplicate:
        doc.status = "Duplicate Flagged"
    elif is_oth:
        doc.status = "Pending MA Approval"
    else:
        doc.status = "AI Reviewed"

    doc.save(ignore_permissions=True)
    frappe.db.commit()


# ─── Flag for MA review (called when user edits AI suggestion fields) ──────────

@frappe.whitelist()
def flag_for_ma_approval(request_name):
    """
    Called client-side when a non-MA user edits an AI suggestion field.
    Transitions the request from AI Reviewed to Pending MA Approval.
    """
    doc = frappe.get_doc("Item Request", request_name)
    if doc.status != "AI Reviewed":
        return {"status": "no_change"}

    doc.status = "Pending MA Approval"
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return {"status": "flagged"}


# ─── Create item (requester accepts AI suggestion as-is) ──────────────────────

@frappe.whitelist()
def create_item_from_request(request_name):
    """
    Called when the requester clicks 'Create Item' after reviewing the AI output.
    Only allowed when status is AI Reviewed (unmodified suggestion).
    Creates the ERPNext Item and marks the request Approved.
    """
    doc = frappe.get_doc("Item Request", request_name)

    if doc.status != "AI Reviewed":
        frappe.throw("Item can only be created directly from 'AI Reviewed' status.")

    item_code = _build_and_insert_item(doc)

    doc.status           = "Approved"
    doc.created_item_code = item_code
    doc.approved_by      = frappe.session.user
    doc.approved_on      = now_datetime()
    doc.save(ignore_permissions=True)
    frappe.db.commit()

    _rebuild_search_index()
    return item_code


# ─── MA approve (MA accepts the request, possibly after editing fields) ────────

@frappe.whitelist()
def approve_request(request_name):
    """
    Called by a Master Approver via the 'Approve & Create Item' button.
    Allowed from Pending MA Approval or Duplicate Flagged status.
    """
    if not _is_ma():
        frappe.throw("Only a Master Approver can approve requests.", frappe.PermissionError)

    doc = frappe.get_doc("Item Request", request_name)

    if doc.status not in ("Pending MA Approval", "Duplicate Flagged"):
        frappe.throw(f"Cannot approve a request in '{doc.status}' status.")

    item_code = _build_and_insert_item(doc)

    doc.status            = "Approved"
    doc.created_item_code = item_code
    doc.approved_by       = frappe.session.user
    doc.approved_on       = now_datetime()
    doc.save(ignore_permissions=True)
    frappe.db.commit()

    _rebuild_search_index()
    return item_code


# ─── MA reject ────────────────────────────────────────────────────────────────

@frappe.whitelist()
def reject_request(request_name, review_note):
    """
    Called by a Master Approver via the 'Reject' button.
    """
    if not _is_ma():
        frappe.throw("Only a Master Approver can reject requests.", frappe.PermissionError)

    if not review_note:
        frappe.throw("A review note is required when rejecting a request.")

    doc = frappe.get_doc("Item Request", request_name)
    doc.status        = "Rejected"
    doc.ma_review_note = review_note
    doc.approved_by   = frappe.session.user
    doc.approved_on   = now_datetime()
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return {"status": "rejected"}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _is_ma():
    roles = frappe.get_roles(frappe.session.user)
    return "Master Approver" in roles or "System Manager" in roles


def _resolve_stock_uom_for_item(doc):
    """Prefer user stock_uom, then AI, then Stock Settings, then Nos."""
    candidates = [
        doc.stock_uom,
        doc.ai_uom_suggestion,
        frappe.db.get_single_value("Stock Settings", "stock_uom"),
        "Nos",
    ]
    for u in candidates:
        if u and frappe.db.exists("UOM", u):
            return u
    fallback = frappe.db.get_value("UOM", {}, "name")
    return fallback or "Nos"


def _resolve_gst_hsn_link_for_item(doc):
    """Return a GST HSN Code document name for Item.gst_hsn_code Link, or empty string."""
    if not frappe.db.exists("DocType", "GST HSN Code"):
        return (doc.gst_hsn_code or doc.ai_hsn_suggestion or "").strip()
    raw = (doc.gst_hsn_code or doc.ai_hsn_suggestion or "").strip()
    if not raw:
        return ""
    if frappe.db.exists("GST HSN Code", raw):
        return raw
    name = frappe.db.get_value("GST HSN Code", {"hsn_code": raw}, "name")
    if name:
        return name
    frappe.log_error(
        title="GST HSN not found for Item",
        message=f"Could not resolve HSN {raw!r} for Item Request {doc.name}",
    )
    return ""


def _build_and_insert_item(doc):
    """
    Creates an ERPNext Item from the AI suggestion fields on the request doc.
    Returns the new item_code.
    """
    if not doc.ai_item_name_suggestion:
        frappe.throw("AI item name suggestion is missing — cannot create item.")
    if not doc.ai_item_group_suggestion:
        frappe.throw("AI item group suggestion is missing — cannot create item.")

    prefix = doc.ai_prefix_suggestion or "GEN"

    # Build a sequential item code: PREFIX-XXXXX
    existing = frappe.db.count("Item", {"item_code": ["like", f"{prefix}-%"]})
    item_code = f"{prefix}-{str(existing + 1).zfill(5)}"

    # Avoid collision in the rare case of gaps/deletions
    while frappe.db.exists("Item", item_code):
        existing += 1
        item_code = f"{prefix}-{str(existing + 1).zfill(5)}"

    stock_uom = _resolve_stock_uom_for_item(doc)
    gst_link = _resolve_gst_hsn_link_for_item(doc)

    if doc.is_fixed_asset and not doc.ai_asset_category_suggestion:
        frappe.throw("Asset Category is required for Fixed Asset items — AI suggestion is missing.")

    item = frappe.get_doc({
        "doctype":           "Item",
        "item_code":         item_code,
        "item_name":         doc.ai_item_name_suggestion,
        "item_group":        doc.ai_item_group_suggestion,
        "is_stock_item":     doc.is_stock_item,
        "is_fixed_asset":    doc.is_fixed_asset,
        "is_purchase_item":  1,
        "stock_uom":         stock_uom,
        "purchase_uom":      stock_uom,
        "gst_hsn_code":      gst_link,
        "asset_category":    doc.ai_asset_category_suggestion or None,
    })

    item.custom_item_request = doc.name

    # Carry over legacy codes if present
    if doc.tally_name:
        item.custom_tally_name = doc.tally_name
    if doc.tally_alias:
        item.custom_tally_alias = doc.tally_alias
    if doc.legacy_material_code:
        item.custom_legacy_code = doc.legacy_material_code

    item.insert(ignore_permissions=True)
    return item_code


def _rebuild_search_index():
    from mpd_customizations.mpd_base.item_ai.dedup import build_search_index
    try:
        build_search_index()
    except Exception:
        frappe.log_error(
            title="Search index rebuild failed after item creation",
            message=frappe.get_traceback(),
        )


def _read_attached_file(doc):
    """
    Reads the file attached to the Item Request (local disk or S3) and returns
    (base64_data_url, mime_type). Call only when attach_documents is set.

    Returns (None, None) if unsupported type or read error (LLM call falls back to text-only).

    Supported: PDF, PNG, JPG/JPEG
    """
    import base64
    import os

    file_url = (doc.attach_documents or "").strip()
    if not file_url:
        return None, None

    ext = os.path.splitext(file_url)[1].lower()
    mime_map = {
        ".pdf":  "application/pdf",
        ".png":  "image/png",
        ".jpg":  "image/jpeg",
        ".jpeg": "image/jpeg",
    }
    mime_type = mime_map.get(ext)
    if not mime_type:
        frappe.log_error(
            title=f"Unsupported attachment type '{ext}' on {doc.name} — skipping",
        )
        return None, None

    try:
        # frappe.get_doc("File", ...).get_content() works for both
        # local files and S3-backed files (frappe_s3_attachment)
        file_doc = frappe.get_doc("File", {"file_url": file_url})
        content  = file_doc.get_content()
        if isinstance(content, str):
            content = content.encode("latin-1")
        encoded      = base64.b64encode(content).decode("ascii")
        data_url     = f"data:{mime_type};base64,{encoded}"
        return data_url, mime_type

    except Exception:
        frappe.log_error(
            title=f"Could not read attachment for Item Request {doc.name}",
            message=frappe.get_traceback(),
        )
        return None, None

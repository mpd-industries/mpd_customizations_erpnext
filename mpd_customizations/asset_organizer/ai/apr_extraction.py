from __future__ import annotations

import base64
import io
import json
import os
import re
import unicodedata

import frappe
from frappe.utils import now_datetime

from mpd_customizations.mpd_base.item_ai.llm_call import call_llm
from mpd_customizations.asset_organizer.ai.schemas import (
    CATEGORY_SCHEMA_MAP,
    CATEGORY_TASK_KEY_MAP,
    PaymentExtractionSchema,
    SegmentationSchema,
)

logger = frappe.logger("asset_organizer")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_file_as_base64(file_url: str) -> tuple[str, str]:
    """
    Given a Frappe file URL, returns (base64_data_url, filename).
    Handles three cases:
      - /private/files/... or /files/...  → read from local filesystem
      - /api/method/frappe_s3_attachment... → fetch via HTTP (S3 presigned redirect)
      - Anything else                       → try as an absolute filesystem path
    """
    import urllib.parse

    # --- Extract filename from URL query string or path ---
    parsed = urllib.parse.urlparse(file_url)
    qs = urllib.parse.parse_qs(parsed.query)
    filename = (
        qs.get("file_name", [None])[0]
        or os.path.basename(parsed.path)
        or "document.pdf"
    )
    mime = "application/pdf" if filename.lower().endswith(".pdf") else "application/octet-stream"

    # --- S3 / API-served file ---
    if "/api/method/" in file_url:
        raw = _fetch_api_file(file_url)
        b64 = base64.b64encode(raw).decode("utf-8")
        return f"data:{mime};base64,{b64}", filename

    # --- Local filesystem file ---
    site_path = frappe.get_site_path()
    if file_url.startswith("/private/files/"):
        abs_path = os.path.join(site_path, file_url.lstrip("/"))
    elif file_url.startswith("/files/"):
        abs_path = os.path.join(site_path, "public", file_url.lstrip("/"))
    else:
        abs_path = file_url

    with open(abs_path, "rb") as fh:
        raw = fh.read()

    b64 = base64.b64encode(raw).decode("utf-8")
    return f"data:{mime};base64,{b64}", filename


def _fetch_api_file(file_url: str) -> bytes:
    """
    Download a file stored in S3 via frappe_s3_attachment.
    Parses the S3 key from the URL and fetches the object directly using
    S3Operations — no HTTP round-trip needed.
    """
    import urllib.parse
    from frappe_s3_attachment.controller import S3Operations

    parsed = urllib.parse.urlparse(file_url)
    qs = urllib.parse.parse_qs(parsed.query)
    key = qs.get("key", [None])[0]
    if not key:
        raise ValueError(f"No 'key' parameter found in S3 file URL: {file_url}")

    s3 = S3Operations()
    response = s3.read_file_from_s3(key)
    return response["Body"].read()


def _get_task_config(task_key: str):
    """Load an AI Task Config by task_key. Raises if missing or inactive."""
    name = frappe.db.get_value("AI Task Config", {"task_key": task_key, "is_active": 1}, "name")
    if not name:
        raise ValueError(f"No active AI Task Config found for task_key={task_key!r}")
    return frappe.get_doc("AI Task Config", name)


# ---------------------------------------------------------------------------
# Normalised string similarity for item catalog matching
# ---------------------------------------------------------------------------

def _normalise(text: str) -> set[str]:
    """Lowercase, strip punctuation/accents, return set of significant words."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-z0-9 ]", " ", text.lower())
    stop = {"the", "a", "an", "of", "and", "or", "for", "with", "to", "in", "at", "by"}
    return {w for w in text.split() if w and w not in stop and len(w) > 1}


def _match_item(raw_description: str) -> tuple[str | None, str | None]:
    """
    Search tabItem for a catalog match.
    Returns (item_name, confidence_label) or (None, None).
    """
    needle_words = _normalise(raw_description)
    if not needle_words:
        return None, None

    # Fetch candidates via LIKE on the first significant word
    first_word = next(iter(sorted(needle_words, key=len, reverse=True)))
    candidates = frappe.db.sql(
        "SELECT name, item_name FROM `tabItem` WHERE item_name LIKE %s LIMIT 50",
        (f"%{first_word}%",),
        as_dict=True,
    )

    best_name = None
    best_score = 0.0
    for row in candidates:
        haystack_words = _normalise(row.item_name)
        if not haystack_words:
            continue
        intersection = needle_words & haystack_words
        score = len(intersection) / max(len(needle_words), len(haystack_words))
        if score > best_score:
            best_score = score
            best_name = row.name

    if best_score >= 0.85:
        return best_name, "Exact Match"
    if best_score >= 0.5:
        return best_name, "Fuzzy Match"
    return None, None


# ---------------------------------------------------------------------------
# HTML summary renderer
# ---------------------------------------------------------------------------

def _render_html_summary(category: str, schema_data: dict) -> str:
    """Returns an inline-styled HTML table summarising the extracted fields."""
    style_table = "border-collapse:collapse;width:100%;font-family:Arial,sans-serif;font-size:12px;"
    style_th = "background:#2c3e50;color:#fff;padding:6px 10px;text-align:left;"
    style_td_key = "padding:5px 10px;border-bottom:1px solid #ddd;font-weight:bold;width:40%;background:#f8f9fa;"
    style_td_val = "padding:5px 10px;border-bottom:1px solid #ddd;"

    doc_desc = schema_data.get("document_description", "")
    rows_html = ""

    skip = {
        "item_lines", "generic_data_map", "extra_fields", "tax",
        "detected_category", "document_description", "summary",
    }
    for key, val in schema_data.items():
        if key in skip or val is None:
            continue
        rows_html += (
            f'<tr>'
            f'<td style="{style_td_key}">{key.replace("_", " ").title()}</td>'
            f'<td style="{style_td_val}">{val}</td>'
            f'</tr>'
        )

    summary = schema_data.get("summary")
    if summary:
        rows_html += (
            f'<tr>'
            f'<td style="{style_td_key}">Summary</td>'
            f'<td style="{style_td_val}">{summary}</td>'
            f'</tr>'
        )

    tax = schema_data.get("tax") or {}
    if tax:
        rows_html += (
            f'<tr><td colspan="2" style="{style_td_key}">Tax Details</td></tr>'
        )
        for tax_key, tax_val in tax.items():
            if tax_val is None:
                continue
            rows_html += (
                f'<tr>'
                f'<td style="{style_td_key}">{tax_key.replace("_", " ").title()}</td>'
                f'<td style="{style_td_val}">{tax_val}</td>'
                f'</tr>'
            )

    extra_fields = schema_data.get("extra_fields") or {}
    if extra_fields:
        rows_html += (
            f'<tr><td colspan="2" style="{style_td_key}">Extra Fields</td></tr>'
        )
        for ef_key, ef_val in extra_fields.items():
            rows_html += (
                f'<tr>'
                f'<td style="{style_td_key}">{ef_key.replace("_", " ").title()}</td>'
                f'<td style="{style_td_val}">{ef_val}</td>'
                f'</tr>'
            )

    # item_lines sub-table
    item_lines = schema_data.get("item_lines", [])
    if item_lines:
        rows_html += (
            f'<tr><td colspan="2" style="{style_td_key}">Item Lines</td></tr>'
        )
        for i, line in enumerate(item_lines, 1):
            desc = line.get("raw_description", "")
            qty = line.get("qty", "")
            uom = line.get("uom", "")
            rate = line.get("rate", "")
            rows_html += (
                f'<tr>'
                f'<td style="{style_td_key}">  Line {i}</td>'
                f'<td style="{style_td_val}">{desc} | Qty: {qty} {uom} | Rate: {rate}</td>'
                f'</tr>'
            )

    return (
        f'<table style="{style_table}">'
        f'<thead><tr>'
        f'<th style="{style_th}" colspan="2">{category} — {doc_desc}</th>'
        f'</tr></thead>'
        f'<tbody>{rows_html}</tbody>'
        f'</table>'
    )


# ---------------------------------------------------------------------------
# Supplier resolution
# ---------------------------------------------------------------------------

def _resolve_supplier(apr_name: str, data: dict) -> None:
    """
    Match extracted supplier GSTIN against tabSupplier. If no match, create
    or reuse a Staged Supplier record. Updates parent APR fields.
    """
    gstin = (data.get("supplier_gstin") or "").strip()
    supplier_name_raw = (data.get("supplier_name") or "").strip()
    address_raw = (data.get("supplier_address") or "").strip()

    if not gstin:
        return

    # Skip if already resolved
    existing_link = frappe.db.get_value("Asset Procurement Record", apr_name, "supplier_link")
    if existing_link:
        return

    # Try live Supplier
    supplier_name = frappe.db.get_value("Supplier", {"gstin": gstin}, "name")
    if supplier_name:
        frappe.db.set_value("Asset Procurement Record", apr_name, {
            "supplier_doctype": "Supplier",
            "supplier_link": supplier_name,
            "supplier_name_raw": supplier_name_raw,
            "supplier_gstin": gstin,
        })
        logger.info(f"APR {apr_name}: matched live Supplier {supplier_name} via GSTIN {gstin}")
        return

    # Check for existing Staged Supplier for this APR
    staged = frappe.db.get_value(
        "Staged Supplier",
        {"extracted_gstin": gstin, "source_apr": apr_name},
        "name",
    )
    if not staged:
        ss_doc = frappe.get_doc({
            "doctype": "Staged Supplier",
            "source_apr": apr_name,
            "raw_supplier_name": supplier_name_raw or gstin,
            "extracted_gstin": gstin,
            "address_raw": address_raw,
            "status": "Pending Review",
        })
        ss_doc.insert(ignore_permissions=True)
        frappe.db.commit()
        staged = ss_doc.name
        logger.info(f"APR {apr_name}: created Staged Supplier {staged} for GSTIN {gstin}")

    frappe.db.set_value("Asset Procurement Record", apr_name, {
        "supplier_doctype": "Staged Supplier",
        "supplier_link": staged,
        "supplier_name_raw": supplier_name_raw,
        "supplier_gstin": gstin,
    })


# ---------------------------------------------------------------------------
# Item line resolution
# ---------------------------------------------------------------------------

def _resolve_item_lines(apr_name: str, category: str, data: dict) -> None:
    """
    For Quote, PO, and Invoice categories, match each item line against the Item
    catalog. Before creating a new row, check whether the line is a duplicate of
    an existing APR item line using TF-IDF pre-filter + LLM confirmation.
    Create Item Request records for genuinely new, unmatched lines.
    """
    if category not in ("Quote", "PO", "Invoice"):
        return

    item_lines = data.get("item_lines") or []
    ref_no = data.get("extracted_ref_no") or data.get("po_number") or data.get("invoice_number") or ""

    apr_doc = frappe.get_doc("Asset Procurement Record", apr_name)

    for line in item_lines:
        raw_desc = (line.get("raw_description") or "").strip()
        if not raw_desc:
            continue

        # Idempotency: skip if this exact line from this ref already exists
        already = any(
            (r.source_document_ref or "") == ref_no and (r.raw_description or "") == raw_desc
            for r in apr_doc.item_lines
        )
        if already:
            continue

        # Dedup check: does this line refer to an item already recorded on this APR
        # from a different source document? (e.g. PO line matches a Quote line)
        existing_descs = [
            r.raw_description
            for r in apr_doc.item_lines
            if (r.raw_description or "").strip() and (r.source_document_ref or "") != ref_no
        ]
        if existing_descs:
            candidates = _find_duplicate_apr_item_line(raw_desc, existing_descs)
            if candidates and _llm_confirm_item_merge(apr_name, raw_desc, candidates):
                logger.info(
                    f"APR {apr_name}: merged '{raw_desc}' into existing line(s) "
                    f"{candidates[:2]} — skipping new row"
                )
                continue

        item_name_match, confidence = _match_item(raw_desc)

        qty = line.get("qty") or 0
        rate = line.get("rate") or 0

        new_row = apr_doc.append("item_lines", {
            "source_document_ref": ref_no,
            "source_category": category,
            "raw_description": raw_desc,
            "hsn_code": line.get("hsn_code"),
            "qty": qty,
            "uom": line.get("uom"),
            "rate": rate,
            "line_total": round((qty or 0) * (rate or 0), 2),
        })

        if item_name_match and confidence:
            new_row.item_doctype = "Item"
            new_row.item_reference = item_name_match
            new_row.match_confidence = confidence
            logger.info(f"APR {apr_name}: matched item '{raw_desc}' → {item_name_match} ({confidence})")
        else:
            # Create Item Request for genuinely new, unrecognised items
            ir = frappe.get_doc({
                "doctype": "Item Request",
                "requester_description": raw_desc,
                "gst_hsn_code": line.get("hsn_code"),
                "reference_doctype": "Asset Procurement Record",
                "reference_name": apr_name,
                "requested_by": "Administrator",
                "status": "Draft",
            })
            ir.insert(ignore_permissions=True)
            frappe.db.commit()
            new_row.item_doctype = "Item Request"
            new_row.item_reference = ir.name
            new_row.match_confidence = "No Match - Request Created"
            logger.info(f"APR {apr_name}: created Item Request {ir.name} for '{raw_desc}'")

    apr_doc.save(ignore_permissions=True)
    frappe.db.commit()


# ---------------------------------------------------------------------------
# Parent field writer (blank-only)
# ---------------------------------------------------------------------------

def _write_parent_fields(apr_name: str, category: str, data: dict) -> None:
    """
    Write extracted milestone/financial fields to the parent APR.
    Only writes to a field if it is currently blank — first clean extraction wins.
    """
    mapping = {
        "Quote": [
            ("quote_date",        data.get("extracted_date")),
            ("quote_total_value", data.get("quote_total_value")),
        ],
        "PO": [
            ("po_date",        data.get("po_date") or data.get("extracted_date")),
            ("po_number",      data.get("po_number") or data.get("extracted_ref_no")),
            ("po_total_value", data.get("po_total_value")),
        ],
        "Invoice": [
            ("invoice_date",           data.get("invoice_date") or data.get("extracted_date")),
            ("invoice_number",         data.get("invoice_number") or data.get("extracted_ref_no")),
            ("invoice_taxable_value",  (data.get("tax") or {}).get("invoice_taxable_value")),
            ("invoice_gst_amount",     (data.get("tax") or {}).get("invoice_gst_amount")),
            ("invoice_total_value",    (data.get("tax") or {}).get("invoice_total_value")),
        ],
        "IGP": [
            ("igp_date",   data.get("igp_date") or data.get("extracted_date")),
            ("igp_number", data.get("igp_number") or data.get("extracted_ref_no")),
        ],
    }

    pairs = mapping.get(category, [])
    for fieldname, value in pairs:
        if value is None:
            continue
        current = frappe.db.get_value("Asset Procurement Record", apr_name, fieldname)
        if current:
            continue
        frappe.db.set_value("Asset Procurement Record", apr_name, fieldname, value)
        logger.debug(f"APR {apr_name}: set {fieldname} = {value}")


# ---------------------------------------------------------------------------
# Asset label generation
# ---------------------------------------------------------------------------

def run_label_generation_job(apr_name: str, trigger_category: str, schema_dict: dict) -> None:
    """
    Called after Quote or PO extraction. Sends extracted item/supplier data to the LLM
    and writes a short human-readable asset_label to the APR.
    Always overwrites — PO extraction produces a richer label than Quote.
    """
    if trigger_category not in ("Quote", "PO"):
        return

    item_lines = schema_dict.get("item_lines") or []
    raw_descriptions = [
        line.get("raw_description", "").strip()
        for line in item_lines
        if line.get("raw_description", "").strip()
    ]

    if not raw_descriptions:
        logger.info(f"APR {apr_name}: no item lines found for label generation, skipping")
        return

    items_text = "\n".join(f"- {d}" for d in raw_descriptions[:6])

    if trigger_category == "PO":
        supplier = schema_dict.get("supplier_name") or ""
        user_prompt = (
            f"Generate a short asset label for this procurement.\n\n"
            f"Supplier: {supplier}\n\n"
            f"Items:\n{items_text}"
        )
    else:
        user_prompt = (
            f"Generate a short asset label for this procurement (no supplier available yet).\n\n"
            f"Items:\n{items_text}"
        )

    try:
        config = _get_task_config("apr_generate_label")
        result = call_llm(
            config=config,
            system_prompt=config.system_prompt,
            user_prompt=user_prompt,
            reference_doctype="Asset Procurement Record",
            reference_name=apr_name,
        )
        label = (result.get("asset_label") or "").strip()
        if label:
            frappe.db.set_value("Asset Procurement Record", apr_name, "asset_label", label)
            logger.info(f"APR {apr_name}: asset_label set to '{label}' (trigger: {trigger_category})")
    except Exception as exc:
        logger.warning(f"APR {apr_name}: label generation failed: {exc}")
        frappe.log_error(title="APR Label Generation Failed", message=frappe.get_traceback())


# ---------------------------------------------------------------------------
# Item line deduplication helpers
# ---------------------------------------------------------------------------

def _find_duplicate_apr_item_line(new_desc: str, existing_descs: list[str]) -> list[str]:
    """
    TF-IDF cosine similarity on existing APR item_lines (in-memory, no Redis).
    Returns list of existing raw_descriptions with similarity score >= 0.3.
    """
    if not existing_descs:
        return []

    try:
        import numpy as np
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity

        corpus = existing_descs + [new_desc]
        vectorizer = TfidfVectorizer(analyzer="word", ngram_range=(1, 2), min_df=1, sublinear_tf=True)
        matrix = vectorizer.fit_transform(corpus)

        query_vec = matrix[-1]
        existing_matrix = matrix[:-1]
        scores = cosine_similarity(query_vec, existing_matrix).flatten()

        return [
            existing_descs[i]
            for i, score in enumerate(scores)
            if float(score) >= 0.3
        ]
    except Exception as exc:
        logger.warning(f"TF-IDF item line check failed: {exc}")
        return []


def _llm_confirm_item_merge(apr_name: str, new_desc: str, candidates: list[str]) -> bool:
    """
    Asks the LLM whether new_desc refers to the same physical item as any of the candidates.
    Returns True if the LLM confirms a match. On any exception → returns False (safe default).
    """
    candidates_text = "\n".join(f"- {c}" for c in candidates)
    user_prompt = (
        f"New item line: \"{new_desc}\"\n\n"
        f"Existing item lines:\n{candidates_text}\n\n"
        "Is the new item line the same physical item as any of the existing ones?"
    )

    try:
        config = _get_task_config("apr_item_line_merge")
        result = call_llm(
            config=config,
            system_prompt=config.system_prompt,
            user_prompt=user_prompt,
            reference_doctype="Asset Procurement Record",
            reference_name=apr_name,
        )
        return bool(result.get("is_same_item"))
    except Exception as exc:
        logger.warning(f"APR {apr_name}: item merge LLM check failed: {exc} — creating new row")
        return False


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

def _advance_state_machine(apr_name: str) -> None:
    """
    Compute and write record_status based on extracted evidence.
    Asset Commissioned is never set here — that is the validate hook's job.
    """
    def _has_category(cat: str) -> bool:
        return bool(frappe.db.get_value(
            "APR Evidence Document",
            {"parent": apr_name, "detected_category": cat, "extraction_status": "Extracted"},
            "name",
        ))

    has_quote = _has_category("Quote")
    has_po    = _has_category("PO")
    has_inv   = _has_category("Invoice")
    has_igp   = _has_category("IGP")

    outstanding   = frappe.db.get_value("Asset Procurement Record", apr_name, "outstanding_balance") or 0
    invoice_total = frappe.db.get_value("Asset Procurement Record", apr_name, "invoice_total_value") or 0
    total_paid    = frappe.db.get_value("Asset Procurement Record", apr_name, "total_amount_paid") or 0

    # Do not override a commissioned status set by validate
    current_status = frappe.db.get_value("Asset Procurement Record", apr_name, "record_status")
    if current_status == "Asset Commissioned":
        return

    if has_po and has_inv and has_igp and invoice_total > 0 and outstanding == 0:
        status = "Insurance Ready"
    elif invoice_total > 0 and outstanding > 0:
        if total_paid == 0:
            status = "Payment Pending"
        elif total_paid < invoice_total:
            status = "Partially Paid"
        else:
            status = "Fully Settled"
    elif has_igp:
        status = "Goods on Site"
    elif has_inv:
        status = "Invoiced"
    elif has_po:
        status = "PO Raised"
    elif has_quote:
        status = "Quotation Captured"
    else:
        status = "Draft"

    frappe.db.set_value("Asset Procurement Record", apr_name, "record_status", status)
    logger.info(f"APR {apr_name}: status → {status}")


# ---------------------------------------------------------------------------
# PDF split helpers
# ---------------------------------------------------------------------------

def _split_pdf(pdf_bytes: bytes, pages: list[int]) -> bytes:
    """Return a new PDF containing only the specified 1-based page numbers."""
    from pypdf import PdfReader, PdfWriter
    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()
    for p in pages:
        writer.add_page(reader.pages[p - 1])
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _save_split_file(apr_name: str, pdf_bytes: bytes, filename: str) -> str:
    """
    Save split PDF bytes as a private Frappe File attached to the APR.
    Returns the file URL.
    """
    file_doc = frappe.get_doc({
        "doctype": "File",
        "file_name": filename,
        "attached_to_doctype": "Asset Procurement Record",
        "attached_to_name": apr_name,
        "is_private": 1,
        "content": pdf_bytes,
    })
    file_doc.insert(ignore_permissions=True)
    frappe.db.commit()
    return file_doc.file_url


def _handle_segmentation(
    apr_name: str,
    upload_row_name: str,
    pdf_bytes: bytes,
    original_filename: str,
    segmentation: SegmentationSchema,
) -> None:
    """
    For each segment in the segmentation result:
      1. Split the PDF to that page range.
      2. Save as a Frappe File.
      3. Append an APR Evidence Document row with detected_category, source_pages, etc.
    Then save the APR (to persist child rows) and enqueue run_evidence_extraction per row.
    Also handles asset_description_suggestion from the first segment.
    """
    apr_doc = frappe.get_doc("Asset Procurement Record", apr_name)
    new_row_names: list[str] = []

    for idx, seg in enumerate(segmentation.segments):
        pages = seg.pages
        page_label = f"{pages[0]}-{pages[-1]}" if len(pages) > 1 else str(pages[0])
        base_name = os.path.splitext(original_filename)[0]
        seg_filename = f"{base_name}_seg{idx + 1}_p{page_label}.pdf"

        try:
            seg_bytes = _split_pdf(pdf_bytes, pages)
            file_url = _save_split_file(apr_name, seg_bytes, seg_filename)
        except Exception as exc:
            logger.error(f"APR {apr_name}: split failed for segment {idx + 1} pages {pages}: {exc}")
            frappe.log_error(title="APR PDF Split Failed", message=frappe.get_traceback())
            continue

        new_row = apr_doc.append("evidence_documents", {
            "evidence_file": file_url,
            "detected_category": seg.category,
            "document_description": seg.description,
            "source_pages": page_label,
            "source_upload": upload_row_name,
            "extraction_status": "Queued",
        })
        new_row_names.append(new_row.name or None)

    apr_doc.save(ignore_permissions=True)
    frappe.db.commit()

    # After save, row names are assigned; collect them from the saved doc
    saved_rows = [
        row for row in frappe.get_doc("Asset Procurement Record", apr_name).evidence_documents
        if row.source_upload == upload_row_name and row.extraction_status == "Queued"
    ]

    # Handle asset_description_suggestion from first segment
    first_seg = segmentation.segments[0] if segmentation.segments else None
    if first_seg and first_seg.asset_description_suggestion:
        other_extracted = frappe.db.count(
            "APR Evidence Document",
            {"parent": apr_name, "extraction_status": "Extracted"},
        )
        if other_extracted == 0:
            if not frappe.db.get_value("Asset Procurement Record", apr_name, "ai_description_suggestion"):
                frappe.db.set_value(
                    "Asset Procurement Record", apr_name,
                    "ai_description_suggestion", first_seg.asset_description_suggestion,
                )
            if not frappe.db.get_value("Asset Procurement Record", apr_name, "asset_description"):
                frappe.db.set_value(
                    "Asset Procurement Record", apr_name,
                    "asset_description", first_seg.asset_description_suggestion,
                )

    # Enqueue extraction for each new evidence row
    for row in saved_rows:
        frappe.db.set_value("APR Evidence Document", row.name, "extraction_status", "Processing")
        frappe.enqueue(
            "mpd_customizations.asset_organizer.ai.apr_extraction.run_evidence_extraction",
            queue="long",
            apr_name=apr_name,
            evidence_row_name=row.name,
        )
        logger.info(f"APR {apr_name}: enqueued extraction for evidence row {row.name} (pages {row.source_pages})")

    frappe.db.commit()


# ---------------------------------------------------------------------------
# Segmentation job (enqueued by controller for each uploaded document)
# ---------------------------------------------------------------------------

def run_segmentation_job(apr_name: str, upload_row_name: str) -> None:
    """
    Background job: segment an uploaded PDF into logical documents.
    Creates one APR Evidence Document row per segment, then enqueues
    run_evidence_extraction for each.
    """
    logger.info(f"run_segmentation_job start: APR={apr_name} upload={upload_row_name}")

    try:
        upload_row = frappe.get_doc("Asset Documentation", upload_row_name)
    except frappe.DoesNotExistError:
        logger.error(f"Upload row {upload_row_name} not found")
        return

    file_url = upload_row.upload_file
    if not file_url:
        frappe.db.set_value("Asset Documentation", upload_row_name, {
            "upload_status": "Failed",
            "upload_error": "No file attached.",
        })
        return

    # Read file bytes (needed for splitting later)
    try:
        file_data_url, filename = _read_file_as_base64(file_url)
        # Decode base64 back to raw bytes for pypdf
        b64_data = file_data_url.split(",", 1)[1]
        pdf_bytes = base64.b64decode(b64_data)
    except Exception as exc:
        frappe.db.set_value("Asset Documentation", upload_row_name, {
            "upload_status": "Failed",
            "upload_error": f"Could not read file: {exc}",
        })
        logger.error(f"APR {apr_name}: file read failed for upload {upload_row_name}: {exc}")
        return

    # Record page count
    try:
        from pypdf import PdfReader
        page_count = len(PdfReader(io.BytesIO(pdf_bytes)).pages)
        frappe.db.set_value("Asset Documentation", upload_row_name, "page_count", page_count)
    except Exception:
        page_count = None

    # Segmentation LLM call
    try:
        segment_config = _get_task_config("apr_document_segment")
        segment_raw = call_llm(
            config=segment_config,
            system_prompt=segment_config.system_prompt,
            user_prompt=(
                f"Segment this PDF document. It has {page_count or 'an unknown number of'} page(s). "
                "Identify every distinct logical document by page range."
            ),
            reference_doctype="Asset Procurement Record",
            reference_name=apr_name,
            attached_file_data=file_data_url,
            attached_mime="application/pdf",
            attached_filename=filename,
        )
        segmentation = SegmentationSchema(**segment_raw)
    except Exception as exc:
        frappe.db.set_value("Asset Documentation", upload_row_name, {
            "upload_status": "Failed",
            "upload_error": f"Segmentation LLM call failed: {exc}",
        })
        logger.error(f"APR {apr_name}: segmentation failed for upload {upload_row_name}: {exc}")
        frappe.log_error(title="APR Segmentation Failed", message=frappe.get_traceback())
        return

    # Split + create evidence rows
    _handle_segmentation(apr_name, upload_row_name, pdf_bytes, filename, segmentation)

    frappe.db.set_value("Asset Documentation", upload_row_name, "upload_status", "Segmented")
    logger.info(
        f"run_segmentation_job complete: APR={apr_name} upload={upload_row_name} "
        f"segments={len(segmentation.segments)}"
    )


# ---------------------------------------------------------------------------
# Main evidence extraction job
# ---------------------------------------------------------------------------

def run_evidence_extraction(apr_name: str, evidence_row_name: str) -> None:
    """
    Background job: full LLM extraction for a single APR Evidence Document row.
    Rows are created by run_segmentation_job and already have detected_category set.
    """
    logger.info(f"run_evidence_extraction start: APR={apr_name} row={evidence_row_name}")

    try:
        ev_row = frappe.get_doc("APR Evidence Document", evidence_row_name)
    except frappe.DoesNotExistError:
        logger.error(f"Evidence row {evidence_row_name} not found")
        return

    file_url = ev_row.evidence_file
    if not file_url:
        frappe.db.set_value("APR Evidence Document", evidence_row_name, {
            "extraction_status": "Failed",
            "extraction_error": "No file attached to this evidence row.",
        })
        return

    try:
        file_data, filename = _read_file_as_base64(file_url)
    except Exception as exc:
        frappe.db.set_value("APR Evidence Document", evidence_row_name, {
            "extraction_status": "Failed",
            "extraction_error": f"Could not read file: {exc}",
        })
        logger.error(f"APR {apr_name}: file read failed for {file_url}: {exc}")
        return

    # detected_category is set by the segmentation job — read it directly
    detected_category = ev_row.detected_category
    if not detected_category:
        frappe.db.set_value("APR Evidence Document", evidence_row_name, {
            "extraction_status": "Failed",
            "extraction_error": "No detected_category set on this evidence row.",
        })
        return

    # If Payment category — route to payment extraction instead
    if detected_category == "Payment":
        logger.info(f"APR {apr_name}: evidence row {evidence_row_name} is Payment — routing to payment extractor")
        frappe.enqueue(
            "mpd_customizations.asset_organizer.ai.apr_extraction.run_payment_extraction",
            queue="long",
            apr_name=apr_name,
            payment_row_name=evidence_row_name,
        )
        return

    # ------------------------------------------------------------------
    # Full extraction
    # ------------------------------------------------------------------
    task_key = CATEGORY_TASK_KEY_MAP.get(detected_category)
    SchemaClass = CATEGORY_SCHEMA_MAP.get(detected_category)

    if not task_key or not SchemaClass:
        frappe.db.set_value("APR Evidence Document", evidence_row_name, {
            "extraction_status": "Failed",
            "extraction_error": f"No extraction schema for category: {detected_category}",
        })
        return

    try:
        extract_config = _get_task_config(task_key)
        extract_raw = call_llm(
            config=extract_config,
            system_prompt=extract_config.system_prompt,
            user_prompt="Extract all fields from this document according to the schema.",
            reference_doctype="Asset Procurement Record",
            reference_name=apr_name,
            attached_file_data=file_data,
            attached_mime="application/pdf",
            attached_filename=filename,
        )
        schema_instance = SchemaClass(**extract_raw)
    except Exception as exc:
        frappe.db.set_value("APR Evidence Document", evidence_row_name, {
            "extraction_status": "Failed",
            "extraction_error": str(exc),
        })
        logger.error(f"APR {apr_name}: extraction pass failed ({task_key}): {exc}")
        frappe.log_error(title=f"APR Extraction Failed [{task_key}]", message=frappe.get_traceback())
        return

    schema_dict = schema_instance.model_dump(mode="json")

    html_summary = _render_html_summary(detected_category, schema_dict)
    generic_data_map = ""
    if detected_category == "Other":
        generic_data_map = json.dumps(schema_dict.get("generic_data_map", {}))

    frappe.db.set_value("APR Evidence Document", evidence_row_name, {
        "extraction_status": "Extracted",
        "extracted_json_vault": json.dumps(schema_dict, indent=2, default=str),
        "extracted_html_summary": html_summary,
        "extracted_date": schema_dict.get("extracted_date"),
        "extracted_ref_no": schema_dict.get("extracted_ref_no"),
        "generic_data_map": generic_data_map,
        "ai_model_used": extract_config.model,
        "extracted_at": now_datetime(),
    })
    frappe.db.commit()

    # Side effects
    _write_parent_fields(apr_name, detected_category, schema_dict)
    _resolve_supplier(apr_name, schema_dict)
    _resolve_item_lines(apr_name, detected_category, schema_dict)
    _advance_state_machine(apr_name)

    # Label generation — only for Quote and PO; enqueued so it doesn't block extraction
    if detected_category in ("Quote", "PO"):
        frappe.enqueue(
            "mpd_customizations.asset_organizer.ai.apr_extraction.run_label_generation_job",
            queue="default",
            apr_name=apr_name,
            trigger_category=detected_category,
            schema_dict=schema_dict,
        )

    logger.info(f"run_evidence_extraction complete: APR={apr_name} row={evidence_row_name} cat={detected_category}")


# ---------------------------------------------------------------------------
# Payment extraction job
# ---------------------------------------------------------------------------

def run_payment_extraction(apr_name: str, payment_row_name: str) -> None:
    """
    Background job: extract payment details from a bank advice / statement PDF.
    Enqueued from the APR controller's on_update hook.
    """
    logger.info(f"run_payment_extraction start: APR={apr_name} row={payment_row_name}")

    try:
        pay_row = frappe.get_doc("APR Payment", payment_row_name)
    except frappe.DoesNotExistError:
        logger.error(f"Payment row {payment_row_name} not found")
        return

    file_url = pay_row.payment_evidence
    if not file_url:
        frappe.db.set_value("APR Payment", payment_row_name, {
            "extraction_status": "Failed",
            "extraction_error": "No payment evidence file attached.",
        })
        return

    try:
        file_data, filename = _read_file_as_base64(file_url)
    except Exception as exc:
        frappe.db.set_value("APR Payment", payment_row_name, {
            "extraction_status": "Failed",
            "extraction_error": f"Could not read file: {exc}",
        })
        return

    # Build matching context from parent APR for is_matched check
    apr_vals = frappe.db.get_value(
        "Asset Procurement Record", apr_name,
        ["supplier_name_raw", "supplier_gstin", "invoice_number", "po_number"],
        as_dict=True,
    ) or {}
    match_context = " | ".join(filter(None, [
        apr_vals.get("supplier_name_raw"),
        apr_vals.get("supplier_gstin"),
        apr_vals.get("invoice_number"),
        apr_vals.get("po_number"),
    ]))

    ref_no = (pay_row.reference_number or "").strip()

    try:
        pay_config = _get_task_config("apr_extract_payment")
        user_prompt = (
            f"Find the transaction with reference number '{ref_no}' "
            f"in this bank statement and extract its amount and date. "
            f"Do not extract amounts from any other transaction. "
            f"If the reference number is not found anywhere in the document, return "
            f"{{\"not_found\": true, \"amount_paid\": null, \"payment_date\": null}}.\n"
            f"Match context (supplier / invoice refs from this APR): {match_context}"
        )
        raw = call_llm(
            config=pay_config,
            system_prompt=pay_config.system_prompt,
            user_prompt=user_prompt,
            reference_doctype="Asset Procurement Record",
            reference_name=apr_name,
            attached_file_data=file_data,
            attached_mime="application/pdf",
            attached_filename=filename,
        )
        schema_instance = PaymentExtractionSchema(**raw)
    except Exception as exc:
        frappe.db.set_value("APR Payment", payment_row_name, {
            "extraction_status": "Failed",
            "extraction_error": str(exc),
        })
        logger.error(f"APR {apr_name}: payment extraction failed: {exc}")
        frappe.log_error(title="APR Payment Extraction Failed", message=frappe.get_traceback())
        return

    sd = schema_instance.model_dump(mode="json")

    if sd.get("not_found"):
        frappe.db.set_value("APR Payment", payment_row_name, {
            "extraction_status": "Failed",
            "extraction_error": (
                f"Reference number '{ref_no}' was not found in the uploaded document. "
                "Please check the file and the reference number and try again."
            ),
        })
        logger.warning(f"APR {apr_name}: payment ref '{ref_no}' not found in document")
        return

    frappe.db.set_value("APR Payment", payment_row_name, {
        "extraction_status": "Extracted",
        "payment_date": sd.get("payment_date"),
        "amount_paid": sd.get("amount_paid"),
        "reference_number": sd.get("reference_number") or ref_no,
        "invoice_reference_in_pdf": sd.get("invoice_reference_in_pdf"),
        "is_matched": 1 if sd.get("is_matched") else 0,
    })
    frappe.db.commit()

    # Recompute totals on parent
    _recompute_payment_totals(apr_name)
    _advance_state_machine(apr_name)

    logger.info(f"run_payment_extraction complete: APR={apr_name} row={payment_row_name}")


def _recompute_payment_totals(apr_name: str) -> None:
    """Sum extracted payment rows and rewrite totals + outstanding on parent."""
    rows = frappe.db.get_all(
        "APR Payment",
        filters={"parent": apr_name, "extraction_status": "Extracted"},
        fields=["amount_paid"],
    )
    total_paid = sum((r.amount_paid or 0) for r in rows)
    invoice_total = frappe.db.get_value("Asset Procurement Record", apr_name, "invoice_total_value") or 0
    outstanding = (invoice_total or 0) - total_paid

    frappe.db.set_value("Asset Procurement Record", apr_name, {
        "total_amount_paid": total_paid,
        "outstanding_balance": outstanding,
    })
    logger.debug(f"APR {apr_name}: total_paid={total_paid} outstanding={outstanding}")

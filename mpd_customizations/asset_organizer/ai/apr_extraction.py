from __future__ import annotations

import base64
import io
import json
import os
import re

import frappe
from frappe.utils import now_datetime

from mpd_customizations.mpd_base.item_ai.dedup import (
    check_item_duplicates,
    check_item_duplicates_and_set_status,
)
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

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".tiff", ".tif", ".bmp"}


def _image_bytes_to_pdf(image_bytes: bytes) -> bytes:
    """Convert raw image bytes to a single-page PDF using Pillow."""
    from PIL import Image

    img = Image.open(io.BytesIO(image_bytes))
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PDF")
    return buf.getvalue()


def _read_file_as_base64(file_url: str) -> tuple[str, str]:
    """
    Given a Frappe file URL, returns (base64_data_url, filename).
    Handles three cases:
      - /private/files/... or /files/...  → read from local filesystem
      - /api/method/frappe_s3_attachment... → fetch via HTTP (S3 presigned redirect)
      - Anything else                       → try as an absolute filesystem path

    Image files (jpg, png, etc.) are automatically converted to single-page PDFs
    so all document types flow through the same PDF code path.
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

    # --- Read raw bytes ---
    if "/api/method/" in file_url:
        raw = _fetch_api_file(file_url)
    else:
        site_path = frappe.get_site_path()
        if file_url.startswith("/private/files/"):
            abs_path = os.path.join(site_path, file_url.lstrip("/"))
        elif file_url.startswith("/files/"):
            abs_path = os.path.join(site_path, "public", file_url.lstrip("/"))
        else:
            abs_path = file_url

        with open(abs_path, "rb") as fh:
            raw = fh.read()

    # --- Convert images to PDF so all uploads share one code path ---
    ext = os.path.splitext(filename)[1].lower()
    if ext in _IMAGE_EXTENSIONS:
        logger.info(f"Converting image '{filename}' to PDF before LLM submission")
        raw = _image_bytes_to_pdf(raw)
        filename = os.path.splitext(filename)[0] + ".pdf"

    b64 = base64.b64encode(raw).decode("utf-8")
    return f"data:application/pdf;base64,{b64}", filename


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
# PO location tree context (for first PO extraction)
# ---------------------------------------------------------------------------

_LOCATION_ROOT = "MPD Ujjain"


def _location_tree_nodes(root_name: str = _LOCATION_ROOT) -> dict[str, dict]:
    root = frappe.db.get_value("Location", {"location_name": root_name}, ["name", "lft", "rgt"], as_dict=True)
    if not root:
        return {}
    rows = frappe.get_all(
        "Location",
        filters={"lft": [">=", root.lft], "rgt": ["<=", root.rgt]},
        fields=["name", "location_name", "parent_location", "lft"],
        order_by="lft asc",
    )
    return {r.name: r for r in rows}


def _build_location_tree_payload(root_name: str = _LOCATION_ROOT) -> dict:
    """
    Build compact nested tree payload for prompt context:
    {"name": "...", "children": [{"name": "...", "children": [...]}, ...]}
    """
    nodes = _location_tree_nodes(root_name)
    if not nodes:
        return {}

    children_by_parent: dict[str | None, list[dict]] = {}
    for node in nodes.values():
        parent = node.get("parent_location")
        children_by_parent.setdefault(parent, []).append(node)

    for lst in children_by_parent.values():
        lst.sort(key=lambda n: (n.get("location_name") or n.get("name") or "").lower())

    root_node = None
    for name, node in nodes.items():
        if (node.get("location_name") or "") == root_name:
            root_node = {**node, "name": name}
            break
    if not root_node:
        return {}

    def _walk(node: dict) -> dict:
        node_name = node.get("name")
        label = node.get("location_name") or node_name
        kids = children_by_parent.get(node_name, [])
        return {
            "name": label,
            "children": [_walk(k) for k in kids],
        }

    return _walk(root_node)


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
# Item line resolution (PO / Invoice only; dedup retrieves, LLM decides)
# ---------------------------------------------------------------------------

def _line_qty_rate_total(line: dict) -> tuple[float, float, float]:
    qty = float(line.get("qty") or 0)
    rate = float(line.get("rate") or 0)
    return qty, rate, round(qty * rate, 2)


def _format_prompt_line(index: str | int, line: dict, source_category: str = "") -> str:
    qty, rate, total = _line_qty_rate_total(line)
    hsn = (line.get("hsn_code") or "—").strip() or "—"
    desc = (line.get("raw_description") or "").strip()
    src = source_category or line.get("source_category") or ""
    src_bit = f" | {src}" if src else ""
    return (
        f"  [{index}] {desc}{src_bit} | qty {qty} | total {total} | "
        f"rate {rate} | hsn {hsn}"
    )


def _row_to_line_dict(row) -> dict:
    return {
        "raw_description": row.raw_description,
        "source_category": row.source_category,
        "source_document_ref": row.source_document_ref,
        "hsn_code": row.hsn_code,
        "qty": row.qty,
        "uom": row.uom,
        "rate": row.rate,
        "line_total": row.line_total,
        "name": row.name,
    }


def _is_same_source_row(row, category: str, ref_no: str) -> bool:
    return (
        (row.source_category or "") == category
        and (row.source_document_ref or "") == ref_no
    )


def _existing_rows_for_merge(apr_doc, category: str, ref_no: str) -> list[dict]:
    """Existing APR lines from other documents, labelled A, B, C…"""
    rows = []
    label = ord("A")
    for row in apr_doc.item_lines:
        if not (row.raw_description or "").strip():
            continue
        if _is_same_source_row(row, category, ref_no):
            continue
        rows.append({
            **_row_to_line_dict(row),
            "prompt_index": chr(label),
            "row": row,
        })
        label += 1
    return rows


def _preferred_description_on_merge(
    existing: dict,
    new_line: dict,
    category: str,
    llm_preferred: str | None,
) -> str:
    """Invoice wording wins over PO when merging lines on the APR."""
    if category == "Invoice":
        return (new_line.get("raw_description") or "").strip()
    if (existing.get("source_category") or "") == "Invoice":
        return (existing.get("raw_description") or "").strip()
    if llm_preferred:
        return llm_preferred.strip()
    return (new_line.get("raw_description") or existing.get("raw_description") or "").strip()


def _preferred_hsn_on_merge(existing: dict, new_line: dict, category: str) -> str | None:
    if category == "Invoice":
        return new_line.get("hsn_code") or existing.get("hsn_code")
    if (existing.get("source_category") or "") == "Invoice":
        return existing.get("hsn_code") or new_line.get("hsn_code")
    return new_line.get("hsn_code") or existing.get("hsn_code")


def _llm_batch_resolve_apr_lines(
    apr_name: str,
    category: str,
    ref_no: str,
    new_lines: list[dict],
    existing_rows: list[dict],
) -> list[dict]:
    """One LLM call: map each new line to add or same-as-existing on this APR."""
    new_block = "\n".join(
        _format_prompt_line(i, line) for i, line in enumerate(new_lines)
    )
    existing_block = "\n".join(
        _format_prompt_line(r["prompt_index"], r) for r in existing_rows
    )
    user_prompt = (
        f"NEW LINES (from {category} ref {ref_no}):\n{new_block}\n\n"
        f"EXISTING LINES (already on this APR):\n{existing_block}\n\n"
        "Return a decision for every new_line_index."
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
        decisions = result.get("decisions") or []
        if isinstance(decisions, list) and decisions:
            return decisions
    except Exception as exc:
        logger.warning(
            f"APR {apr_name}: batch item merge LLM failed: {exc} — defaulting to add"
        )
        frappe.log_error(
            title=f"APR Item Line Merge Failed [{apr_name}]",
            message=frappe.get_traceback(),
        )

    return [{"new_line_index": i, "action": "add"} for i in range(len(new_lines))]


def _find_existing_by_prompt_index(existing_rows: list[dict], index: str) -> dict | None:
    for row in existing_rows:
        if row.get("prompt_index") == index:
            return row
    return None


def _update_existing_apr_row(
    existing_entry: dict,
    new_line: dict,
    category: str,
    preferred_description: str,
) -> None:
    row = existing_entry["row"]
    row.raw_description = preferred_description
    hsn = _preferred_hsn_on_merge(existing_entry, new_line, category)
    if hsn and not row.hsn_code:
        row.hsn_code = hsn
    if new_line.get("uom") and not row.uom:
        row.uom = new_line.get("uom")
    if new_line.get("rate") and not row.rate:
        row.rate = new_line.get("rate")
    qty, rate, total = _line_qty_rate_total(new_line)
    if qty and not row.qty:
        row.qty = qty
    if total and not row.line_total:
        row.line_total = total


def _format_catalog_candidates(candidates: list[dict]) -> str:
    lines = []
    for c in candidates:
        hsn = c.get("gst_hsn_code") or "—"
        score = c.get("similarity_score", "")
        lines.append(
            f"  - {c.get('name')}: {c.get('item_name')} "
            f"[{c.get('item_group', '')}] (score {score}, hsn {hsn})"
        )
    return "\n".join(lines) if lines else "  (none above threshold)"


def _llm_resolve_catalog_item(
    apr_name: str,
    line: dict,
    candidates: list[dict],
) -> tuple[str | None, bool]:
    """
    LLM picks an Item from dedup candidates or declares a new product.
    Returns (item_code, is_existing_item).
    """
    qty, rate, total = _line_qty_rate_total(line)
    desc = (line.get("raw_description") or "").strip()
    hsn = line.get("hsn_code") or "—"
    user_prompt = (
        f"LINE:\n{_format_prompt_line('?', line)}\n\n"
        f"CANDIDATES (from similarity search):\n"
        f"{_format_catalog_candidates(candidates)}\n"
    )

    try:
        config = _get_task_config("apr_item_catalog_match")
        result = call_llm(
            config=config,
            system_prompt=config.system_prompt,
            user_prompt=user_prompt,
            reference_doctype="Asset Procurement Record",
            reference_name=apr_name,
        )
        if result.get("is_existing_item"):
            code = (result.get("matched_item_code") or "").strip()
            valid = {c.get("name") for c in candidates}
            if code and code in valid:
                return code, True
            logger.warning(
                f"APR {apr_name}: catalog LLM returned invalid item {code!r} for '{desc}'"
            )
        return None, False
    except Exception as exc:
        logger.warning(f"APR {apr_name}: catalog match LLM failed for '{desc}': {exc}")
        frappe.log_error(
            title=f"APR Catalog Match Failed [{apr_name}]",
            message=frappe.get_traceback(),
        )
        return None, False


def _extract_source_item_code(raw_description: str) -> str | None:
    """Extract a leading equipment/item code like VCS00001."""
    desc = (raw_description or "").strip()
    if not desc:
        return None
    first_line = desc.splitlines()[0].strip()
    match = re.match(r"^([A-Z]{2,}[A-Z0-9\-_/]{2,})\b", first_line)
    return match.group(1) if match else None


def _normalize_desc_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in (text or "").splitlines():
        cleaned = re.sub(r"\s+", " ", raw).strip()
        if cleaned:
            lines.append(cleaned)
    return lines


def _description_token_set(text: str) -> set[str]:
    return {
        t.lower()
        for t in re.findall(r"[A-Za-z0-9]+", text or "")
        if len(t) > 2
    }


def _collect_evidence_description_variants(
    apr_name: str,
    primary_description: str,
    source_item_code: str | None,
) -> list[str]:
    """Collect related PO/Invoice item descriptions from extracted evidence JSON."""
    variants: list[str] = []
    primary_tokens = _description_token_set(primary_description)
    rows = frappe.get_all(
        "APR Evidence Document",
        filters={
            "parent": apr_name,
            "extraction_status": "Extracted",
            "detected_category": ["in", ["PO", "Invoice"]],
        },
        fields=["name", "extracted_json_vault"],
    )
    for row in rows:
        payload = row.extracted_json_vault
        if not payload:
            continue
        try:
            data = json.loads(payload)
        except Exception:
            continue
        for item_line in (data.get("item_lines") or []):
            desc = (item_line.get("raw_description") or "").strip()
            if not desc:
                continue
            if source_item_code and source_item_code.lower() in desc.lower():
                variants.append(desc)
                continue
            overlap = primary_tokens.intersection(_description_token_set(desc))
            if len(overlap) >= 2:
                variants.append(desc)
    return variants


def _build_canonical_item_request_description(
    apr_name: str,
    apr_row,
    line: dict,
) -> tuple[str, str | None]:
    """
    Build a rich Item Request description using merged line context:
    consolidated APR line + related PO/Invoice evidence variants.
    """
    primary = (line.get("raw_description") or "").strip()
    source_item_code = _extract_source_item_code(primary)

    variant_pool = [primary]
    # Include current APR row description (may already be merged by PO/Invoice logic)
    row_desc = (apr_row.raw_description or "").strip()
    if row_desc:
        variant_pool.append(row_desc)
    variant_pool.extend(
        _collect_evidence_description_variants(apr_name, primary, source_item_code)
    )

    # Deduplicate while preserving order
    unique_variants: list[str] = []
    seen: set[str] = set()
    for variant in variant_pool:
        key = re.sub(r"\s+", " ", variant).strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        unique_variants.append(variant.strip())

    lead_text = unique_variants[0] if unique_variants else primary
    if source_item_code:
        lead_text = re.sub(
            rf"^\s*{re.escape(source_item_code)}\s*[-:|]?\s*",
            "",
            lead_text,
            flags=re.IGNORECASE,
        ).strip()
    headline = (
        f"{source_item_code} - {lead_text}" if source_item_code and lead_text else lead_text
    )

    detail_lines: list[str] = []
    for variant in unique_variants:
        if source_item_code:
            variant = re.sub(
                rf"^\s*{re.escape(source_item_code)}\s*[-:|]?\s*",
                "",
                variant,
                flags=re.IGNORECASE,
            ).strip()
        for ln in _normalize_desc_lines(variant):
            if ln and ln.lower() != (headline or "").lower():
                detail_lines.append(ln)

    # Unique detail lines
    final_details: list[str] = []
    seen_details: set[str] = set()
    for ln in detail_lines:
        key = ln.lower()
        if key in seen_details:
            continue
        seen_details.add(key)
        final_details.append(ln)

    qty, rate, line_total = _line_qty_rate_total(line)
    hsn = (line.get("hsn_code") or "").strip()
    uom = (line.get("uom") or "").strip()
    source_ref = (apr_row.source_document_ref or "").strip()
    source_cat = (apr_row.source_category or "").strip()

    meta_parts = []
    if hsn:
        meta_parts.append(f"HSN: {hsn}")
    if qty:
        qty_text = f"{qty:g}"
        if uom:
            qty_text = f"{qty_text} {uom}"
        meta_parts.append(f"Qty: {qty_text}")
    if rate:
        meta_parts.append(f"Rate: {rate:g}")
    if line_total:
        meta_parts.append(f"Line Total: {line_total:g}")
    if source_ref:
        source_label = f"{source_cat} " if source_cat else ""
        meta_parts.append(f"Source: {source_label}{source_ref}".strip())

    parts = [headline] if headline else []
    if final_details:
        parts.append("\n".join(final_details[:20]))
    if meta_parts:
        parts.append(" | ".join(meta_parts))

    canonical_description = "\n".join(p for p in parts if p).strip()
    return canonical_description or primary, source_item_code


def _link_catalog_or_item_request(
    apr_name: str,
    apr_row,
    line: dict,
) -> None:
    """dedup.py retrieves candidates; LLM confirms Item link or Item Request."""
    if (apr_row.item_doctype or "") == "Item" and apr_row.item_reference:
        return

    desc = (line.get("raw_description") or "").strip()
    if not desc:
        return

    candidates = check_item_duplicates(
        description=desc,
        hsn_code=line.get("hsn_code"),
    )
    item_code, is_existing = _llm_resolve_catalog_item(apr_name, line, candidates)

    if is_existing and item_code:
        apr_row.item_doctype = "Item"
        apr_row.item_reference = item_code
        apr_row.match_confidence = "Exact Match"
        logger.info(f"APR {apr_name}: catalog LLM linked '{desc}' → {item_code}")
        return

    canonical_desc, source_item_code = _build_canonical_item_request_description(
        apr_name,
        apr_row,
        line,
    )

    ir = frappe.get_doc({
        "doctype": "Item Request",
        "requester_description": canonical_desc,
        "combined_asset_description": canonical_desc,
        "source_item_code": source_item_code,
        "gst_hsn_code": line.get("hsn_code"),
        "is_fixed_asset": 1,
        "reference_doctype": "Asset Procurement Record",
        "reference_name": apr_name,
        "requested_by": "Administrator",
        "status": "Draft",
    })
    ir.insert(ignore_permissions=True)
    check_item_duplicates_and_set_status(
        ir.name,
        canonical_desc,
        hsn_code=line.get("hsn_code"),
    )
    apr_row.item_doctype = "Item Request"
    apr_row.item_reference = ir.name
    apr_row.match_confidence = "No Match - Request Created"
    logger.info(f"APR {apr_name}: created Item Request {ir.name} for '{desc}'")


def _append_apr_item_line(apr_doc, category: str, ref_no: str, line: dict):
    qty, rate, total = _line_qty_rate_total(line)
    row = apr_doc.append("item_lines", {
        "source_document_ref": ref_no,
        "source_category": category,
        "raw_description": (line.get("raw_description") or "").strip(),
        "hsn_code": line.get("hsn_code"),
        "qty": qty,
        "uom": line.get("uom"),
        "rate": rate,
        "line_total": total,
    })
    line_with_desc = {**line, "raw_description": row.raw_description}
    _link_catalog_or_item_request(apr_doc.name, row, line_with_desc)
    return row


def _resolve_item_lines(apr_name: str, category: str, data: dict) -> None:
    """
    PO and Invoice only. Batch LLM merges against existing APR lines; dedup.py +
    catalog LLM links Items or creates Item Requests for new lines.
    """
    if category not in ("PO", "Invoice"):
        return

    item_lines = data.get("item_lines") or []
    ref_no = data.get("extracted_ref_no") or data.get("po_number") or data.get("invoice_number") or ""

    apr_doc = frappe.get_doc("Asset Procurement Record", apr_name)

    new_lines: list[dict] = []
    for line in item_lines:
        raw_desc = (line.get("raw_description") or "").strip()
        if not raw_desc:
            continue
        if any(
            _is_same_source_row(r, category, ref_no)
            and (r.raw_description or "").strip() == raw_desc
            for r in apr_doc.item_lines
        ):
            continue
        new_lines.append(line)

    if not new_lines:
        return

    existing_rows = _existing_rows_for_merge(apr_doc, category, ref_no)

    if existing_rows:
        decisions = _llm_batch_resolve_apr_lines(
            apr_name, category, ref_no, new_lines, existing_rows
        )
    else:
        decisions = [{"new_line_index": i, "action": "add"} for i in range(len(new_lines))]

    matched_existing_indices: set[str] = set()

    for decision in decisions:
        idx = decision.get("new_line_index")
        if idx is None or idx < 0 or idx >= len(new_lines):
            continue
        new_line = new_lines[idx]
        action = (decision.get("action") or "add").strip().lower()

        if action == "same":
            matched_idx = (decision.get("matched_existing_index") or "").strip()
            existing_entry = _find_existing_by_prompt_index(existing_rows, matched_idx)
            if not existing_entry or matched_idx in matched_existing_indices:
                logger.warning(
                    f"APR {apr_name}: invalid merge index {matched_idx!r} — adding line"
                )
                _append_apr_item_line(apr_doc, category, ref_no, new_line)
                continue
            matched_existing_indices.add(matched_idx)
            preferred = _preferred_description_on_merge(
                existing_entry,
                new_line,
                category,
                decision.get("preferred_description"),
            )
            _update_existing_apr_row(existing_entry, new_line, category, preferred)
            merge_line = {**new_line, "raw_description": preferred}
            _link_catalog_or_item_request(apr_name, existing_entry["row"], merge_line)
            logger.info(
                f"APR {apr_name}: merged line [{idx}] into existing [{matched_idx}]"
            )
        else:
            _append_apr_item_line(apr_doc, category, ref_no, new_line)

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
            ("main_location", data.get("main_location")),
            ("level_1_location", data.get("level_1_location")),
            ("level_2_location", data.get("level_2_location")),
            ("level_3_location", data.get("level_3_location")),
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


# ---------------------------------------------------------------------------
# Extraction ordering (APR-level chain)
# ---------------------------------------------------------------------------

CATEGORY_PRIORITY: dict[str, int] = {
    "Quote": 1,
    "PO": 2,
    "IGP": 3,
    "Weighment Slip": 4,
    "Invoice": 5,
    "Lorry Receipt": 6,
    "E-Way Bill": 7,
    "Payment": 8,
    "Other": 9,
}
_DEFAULT_CATEGORY_PRIORITY = 10

_CACHE_PENDING_SEGMENTS = "apr_pending_segments:{apr_name}"
_CACHE_CHAIN_ACTIVE = "apr_extraction_chain_active:{apr_name}"


def _category_priority(category: str | None) -> int:
    return CATEGORY_PRIORITY.get(category or "", _DEFAULT_CATEGORY_PRIORITY)


def _source_pages_sort_key(source_pages: str | None) -> tuple:
    """Sort page ranges like '1', '2-3' numerically by first page."""
    if not source_pages:
        return (0,)
    first = str(source_pages).split("-")[0].strip()
    try:
        return (int(first), source_pages)
    except ValueError:
        return (0, source_pages or "")


def _sort_evidence_rows(rows: list[dict]) -> list[dict]:
    return sorted(
        rows,
        key=lambda r: (
            _category_priority(r.get("detected_category")),
            _source_pages_sort_key(r.get("source_pages")),
            r.get("name") or "",
        ),
    )


def set_pending_segmentations(apr_name: str, count: int) -> None:
    frappe.cache().set(_CACHE_PENDING_SEGMENTS.format(apr_name=apr_name), int(count))


def increment_pending_segmentations(apr_name: str, count: int) -> None:
    key = _CACHE_PENDING_SEGMENTS.format(apr_name=apr_name)
    existing = int(frappe.cache().get(key) or 0)
    frappe.cache().set(key, existing + int(count))


def _on_segmentation_complete(apr_name: str) -> None:
    key = _CACHE_PENDING_SEGMENTS.format(apr_name=apr_name)
    pending = frappe.cache().get(key)
    if pending is not None:
        pending = int(pending)
        if pending > 1:
            frappe.cache().set(key, pending - 1)
            logger.info(
                f"APR {apr_name}: segmentation complete, {pending - 1} upload(s) still pending"
            )
            return
        frappe.cache().delete(key)
        logger.info(f"APR {apr_name}: all segmentations complete — starting extraction chain")
    start_apr_extraction_chain(apr_name)


def _is_extraction_chain_active(apr_name: str) -> bool:
    return bool(frappe.cache().get(_CACHE_CHAIN_ACTIVE.format(apr_name=apr_name)))


def start_apr_extraction_chain(apr_name: str) -> None:
    """Begin ordered evidence extraction for all Queued rows on this APR."""
    chain_key = _CACHE_CHAIN_ACTIVE.format(apr_name=apr_name)
    if frappe.cache().get(chain_key):
        logger.info(f"APR {apr_name}: extraction chain already active")
        return

    queued = frappe.get_all(
        "APR Evidence Document",
        filters={"parent": apr_name, "extraction_status": "Queued"},
        fields=["name"],
        limit=1,
    )
    if not queued:
        logger.info(f"APR {apr_name}: no queued evidence rows — skipping chain start")
        return

    frappe.cache().set(chain_key, 1)
    _enqueue_next_evidence(apr_name)


def _clear_extraction_chain(apr_name: str) -> None:
    frappe.cache().delete(_CACHE_CHAIN_ACTIVE.format(apr_name=apr_name))


def _enqueue_next_evidence(apr_name: str) -> None:
    """Enqueue the next Queued evidence row in category priority order."""
    if not _is_extraction_chain_active(apr_name):
        return

    rows = frappe.get_all(
        "APR Evidence Document",
        filters={"parent": apr_name, "extraction_status": "Queued"},
        fields=["name", "detected_category", "source_pages"],
    )
    if not rows:
        _clear_extraction_chain(apr_name)
        logger.info(f"APR {apr_name}: extraction chain complete")
        return

    next_row = _sort_evidence_rows(rows)[0]
    frappe.db.set_value("APR Evidence Document", next_row.name, {
        "extraction_status": "Processing",
        "extraction_error": None,
    })
    frappe.enqueue(
        "mpd_customizations.asset_organizer.ai.apr_extraction.run_evidence_extraction",
        queue="long",
        apr_name=apr_name,
        evidence_row_name=next_row.name,
        continue_chain=True,
    )
    logger.info(
        f"APR {apr_name}: chained extraction → {next_row.name} "
        f"({next_row.detected_category}, pages {next_row.source_pages})"
    )


def _maybe_continue_extraction_chain(apr_name: str, continue_chain: bool) -> None:
    if continue_chain and _is_extraction_chain_active(apr_name):
        _enqueue_next_evidence(apr_name)


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

    frappe.db.commit()


# ---------------------------------------------------------------------------
# Segmentation job (enqueued by controller for each uploaded document)
# ---------------------------------------------------------------------------

def run_segmentation_job(apr_name: str, upload_row_name: str) -> None:
    """
    Background job: segment an uploaded PDF into logical documents.
    Creates one APR Evidence Document row per segment; extraction is started
    via the APR-level chain when all pending segmentations for this batch finish.
    """
    logger.info(f"run_segmentation_job start: APR={apr_name} upload={upload_row_name}")

    try:
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

        try:
            file_data_url, filename = _read_file_as_base64(file_url)
            b64_data = file_data_url.split(",", 1)[1]
            pdf_bytes = base64.b64decode(b64_data)
        except Exception as exc:
            frappe.db.set_value("Asset Documentation", upload_row_name, {
                "upload_status": "Failed",
                "upload_error": f"Could not read file: {exc}",
            })
            logger.error(f"APR {apr_name}: file read failed for upload {upload_row_name}: {exc}")
            return

        try:
            from pypdf import PdfReader
            page_count = len(PdfReader(io.BytesIO(pdf_bytes)).pages)
            frappe.db.set_value("Asset Documentation", upload_row_name, "page_count", page_count)
        except Exception:
            page_count = None

        try:
            segment_config = _get_task_config("apr_document_segment")
            segment_raw = call_llm(
                config=segment_config,
                system_prompt=segment_config.system_prompt,
                user_prompt=(
                    f"Segment this PDF document. It has {page_count or 'an unknown number of'} "
                    "page(s). Identify every distinct logical document by page range."
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

        _handle_segmentation(apr_name, upload_row_name, pdf_bytes, filename, segmentation)

        frappe.db.set_value("Asset Documentation", upload_row_name, "upload_status", "Segmented")
        logger.info(
            f"run_segmentation_job complete: APR={apr_name} upload={upload_row_name} "
            f"segments={len(segmentation.segments)}"
        )
    finally:
        _on_segmentation_complete(apr_name)


# ---------------------------------------------------------------------------
# Main evidence extraction job
# ---------------------------------------------------------------------------

def run_evidence_extraction(
    apr_name: str,
    evidence_row_name: str,
    continue_chain: bool = False,
) -> None:
    """
    Background job: full LLM extraction for a single APR Evidence Document row.
    Rows are created by run_segmentation_job and already have detected_category set.
    When continue_chain=True, the next Queued row is enqueued after this job finishes.
    """
    logger.info(f"run_evidence_extraction start: APR={apr_name} row={evidence_row_name}")

    try:
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

        detected_category = ev_row.detected_category
        if not detected_category:
            frappe.db.set_value("APR Evidence Document", evidence_row_name, {
                "extraction_status": "Failed",
                "extraction_error": "No detected_category set on this evidence row.",
            })
            return

        if detected_category == "Payment":
            logger.info(
                f"APR {apr_name}: evidence row {evidence_row_name} is Payment — "
                "routing to payment extractor"
            )
            frappe.enqueue(
                "mpd_customizations.asset_organizer.ai.apr_extraction.run_payment_extraction",
                queue="long",
                apr_name=apr_name,
                payment_row_name=evidence_row_name,
            )
            return

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
            user_prompt = "Extract all fields from this document according to the schema."
            if detected_category == "PO":
                location_tree = _build_location_tree_payload(_LOCATION_ROOT)
                if location_tree:
                    user_prompt = (
                        "Extract all fields from this purchase order according to the schema.\n\n"
                        "Use the LOCATION TREE below for location fields. "
                        "Choose location values only from this tree. "
                        "If no reliable match is present in the document, set those fields to null.\n\n"
                        f"LOCATION TREE (JSON):\n{json.dumps(location_tree, ensure_ascii=False)}"
                    )
            extract_raw = call_llm(
                config=extract_config,
                system_prompt=extract_config.system_prompt,
                user_prompt=user_prompt,
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
            frappe.log_error(
                title=f"APR Extraction Failed [{task_key}]",
                message=frappe.get_traceback(),
            )
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
            "main_location": schema_dict.get("main_location"),
            "level_1_location": schema_dict.get("level_1_location"),
            "level_2_location": schema_dict.get("level_2_location"),
            "level_3_location": schema_dict.get("level_3_location"),
            "generic_data_map": generic_data_map,
            "ai_model_used": extract_config.model,
            "extracted_at": now_datetime(),
        })
        frappe.db.commit()

        _write_parent_fields(apr_name, detected_category, schema_dict)
        _resolve_supplier(apr_name, schema_dict)
        _resolve_item_lines(apr_name, detected_category, schema_dict)
        _advance_state_machine(apr_name)

        if detected_category in ("Quote", "PO"):
            frappe.enqueue(
                "mpd_customizations.asset_organizer.ai.apr_extraction.run_label_generation_job",
                queue="default",
                apr_name=apr_name,
                trigger_category=detected_category,
                schema_dict=schema_dict,
            )

        logger.info(
            f"run_evidence_extraction complete: APR={apr_name} row={evidence_row_name} "
            f"cat={detected_category}"
        )
    finally:
        _maybe_continue_extraction_chain(apr_name, continue_chain)


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

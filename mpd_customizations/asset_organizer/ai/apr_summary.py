from __future__ import annotations

import base64
import io
import json
import os
import re

import frappe

from mpd_customizations.asset_organizer.ai import logger
from frappe.utils import now_datetime

from mpd_customizations.mpd_base.item_ai.dedup import (
    check_item_duplicates,
    check_item_duplicates_and_set_status,
)
from mpd_customizations.mpd_base.ai.llm import call_llm
from mpd_customizations.asset_organizer.ai.schemas import (
    CATEGORY_SCHEMA_MAP,
    CATEGORY_TASK_KEY_MAP,
    PaymentExtractionSchema,
    SegmentationSchema,
)


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


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
from mpd_customizations.asset_organizer.ai.apr_context import (
    _get_task_config,
)
from mpd_customizations.asset_organizer.ai.schemas import (
    CATEGORY_SCHEMA_MAP,
    CATEGORY_TASK_KEY_MAP,
    PaymentExtractionSchema,
    SegmentationSchema,
)


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


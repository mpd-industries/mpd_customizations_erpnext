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
from mpd_customizations.asset_organizer.ai.apr_file_io import (
    _read_file_as_base64,
)
from mpd_customizations.asset_organizer.ai.apr_parent_fields import (
    _advance_state_machine,
)
from mpd_customizations.asset_organizer.ai.schemas import (
    CATEGORY_SCHEMA_MAP,
    CATEGORY_TASK_KEY_MAP,
    PaymentExtractionSchema,
    SegmentationSchema,
)


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


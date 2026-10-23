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
from mpd_customizations.asset_organizer.ai.apr_chain import (
    _maybe_continue_extraction_chain,
)
from mpd_customizations.asset_organizer.ai.apr_context import (
    _LOCATION_ROOT,
    _build_location_tree_payload,
    _get_task_config,
)
from mpd_customizations.asset_organizer.ai.apr_file_io import (
    _read_file_as_base64,
)
from mpd_customizations.asset_organizer.ai.apr_item_lines import (
    _resolve_item_lines,
)
from mpd_customizations.asset_organizer.ai.apr_parent_fields import (
    _advance_state_machine,
    _write_parent_fields,
)
from mpd_customizations.asset_organizer.ai.apr_summary import (
    _render_html_summary,
    _resolve_supplier,
)
from mpd_customizations.asset_organizer.ai.schemas import (
    CATEGORY_SCHEMA_MAP,
    CATEGORY_TASK_KEY_MAP,
    PaymentExtractionSchema,
    SegmentationSchema,
)


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


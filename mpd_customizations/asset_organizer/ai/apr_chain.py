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


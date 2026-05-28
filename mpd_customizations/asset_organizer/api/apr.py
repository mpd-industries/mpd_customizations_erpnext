import json

import frappe
from frappe import _

from mpd_customizations.asset_organizer.ai.apr_extraction import (
    _clear_extraction_chain,
    set_pending_segmentations,
)

logger = frappe.logger("asset_organizer")

_ALLOWED_REQUEUE_ROLES = {"System Manager", "Stock Manager"}

_APR_DERIVED_FIELDS = {
    "quote_date": None,
    "po_date": None,
    "po_number": None,
    "invoice_date": None,
    "invoice_number": None,
    "igp_date": None,
    "igp_number": None,
    "quote_total_value": None,
    "po_total_value": None,
    "invoice_taxable_value": None,
    "invoice_gst_amount": None,
    "invoice_total_value": None,
    "supplier_doctype": None,
    "supplier_link": None,
    "supplier_gstin": None,
    "supplier_name_raw": None,
    "asset_label": None,
    "ai_description_suggestion": None,
    "record_status": "Draft",
}


def _check_rerun_permission() -> None:
    user_roles = set(frappe.get_roles(frappe.session.user))
    if not (user_roles & _ALLOWED_REQUEUE_ROLES):
        frappe.throw(
            _("Only System Manager or Stock Manager may run extraction actions."),
            frappe.PermissionError,
        )


def _parse_apr_names(apr_names) -> list[str]:
    if isinstance(apr_names, str):
        apr_names = json.loads(apr_names)
    if not apr_names:
        frappe.throw(_("No records selected."))
    return list(apr_names)


def _delete_evidence_files(apr_doc) -> None:
    for row in apr_doc.evidence_documents:
        if not row.evidence_file:
            continue
        file_name = frappe.db.get_value("File", {"file_url": row.evidence_file}, "name")
        if file_name:
            try:
                frappe.delete_doc("File", file_name, ignore_permissions=True, force=True)
            except Exception as exc:
                logger.warning(f"Could not delete file {file_name}: {exc}")


def _reset_apr_evidence_data(apr_doc) -> int:
    """Clear evidence rows, item lines, and document-derived APR fields. Returns upload count."""
    _delete_evidence_files(apr_doc)

    apr_doc.evidence_documents = []
    apr_doc.item_lines = []
    for fieldname, value in _APR_DERIVED_FIELDS.items():
        setattr(apr_doc, fieldname, value)

    upload_count = 0
    for row in apr_doc.uploaded_documents:
        if not row.upload_file:
            continue
        upload_count += 1
        row.upload_status = "Queued"
        row.page_count = None
        row.upload_error = None

    apr_doc.save(ignore_permissions=True)
    frappe.db.commit()
    return upload_count


def _enqueue_apr_segmentation_jobs(apr_name: str) -> int:
    """Enqueue segmentation for all uploads with files. Returns number of jobs queued."""
    upload_rows = frappe.get_all(
        "Asset Documentation",
        filters={"parent": apr_name, "parenttype": "Asset Procurement Record"},
        fields=["name", "upload_file", "upload_status"],
    )
    to_run = [r for r in upload_rows if r.upload_file]
    if not to_run:
        return 0

    _clear_extraction_chain(apr_name)
    set_pending_segmentations(apr_name, len(to_run))

    for row in to_run:
        frappe.db.set_value("Asset Documentation", row.name, "upload_status", "Processing")
        frappe.enqueue(
            "mpd_customizations.asset_organizer.ai.apr_extraction.run_segmentation_job",
            queue="long",
            apr_name=apr_name,
            upload_row_name=row.name,
        )
        logger.info(f"APR {apr_name}: enqueued segmentation for upload {row.name}")

    frappe.db.commit()
    return len(to_run)


@frappe.whitelist()
def requeue_evidence_extraction(evidence_row_name: str) -> dict:
    """
    Reset an evidence row to Queued and re-enqueue background extraction.
    Requires System Manager or Stock Manager role.
    """
    _check_rerun_permission()

    row = frappe.get_doc("APR Evidence Document", evidence_row_name)
    apr_name = row.parent

    frappe.db.set_value("APR Evidence Document", evidence_row_name, {
        "extraction_status": "Processing",
        "extraction_error": None,
    })

    frappe.enqueue(
        "mpd_customizations.asset_organizer.ai.apr_extraction.run_evidence_extraction",
        queue="long",
        apr_name=apr_name,
        evidence_row_name=evidence_row_name,
        continue_chain=False,
    )
    logger.info(
        f"requeue_evidence_extraction: APR={apr_name} row={evidence_row_name} "
        f"by {frappe.session.user}"
    )
    return {"status": "queued"}


@frappe.whitelist()
def rerun_full_apr_extraction(apr_name: str) -> dict:
    """
    Full evidence pipeline rerun: reset derived document data, re-segment all uploads,
    then extract evidence in category order. Does not touch payment rows.
    """
    _check_rerun_permission()

    if not frappe.db.exists("Asset Procurement Record", apr_name):
        frappe.throw(_("Asset Procurement Record {0} not found").format(apr_name))

    apr_doc = frappe.get_doc("Asset Procurement Record", apr_name)
    upload_count = _reset_apr_evidence_data(apr_doc)
    jobs_queued = _enqueue_apr_segmentation_jobs(apr_name)

    logger.info(
        f"rerun_full_apr_extraction: APR={apr_name} uploads={upload_count} "
        f"jobs={jobs_queued} by {frappe.session.user}"
    )
    return {
        "status": "queued",
        "apr_name": apr_name,
        "uploads": upload_count,
        "segmentation_jobs": jobs_queued,
    }


@frappe.whitelist()
def rerun_full_apr_extraction_bulk(apr_names) -> dict:
    """Bulk full evidence rerun for multiple APRs."""
    _check_rerun_permission()
    names = _parse_apr_names(apr_names)
    results = []
    errors = []

    for apr_name in names:
        try:
            result = rerun_full_apr_extraction(apr_name)
            results.append(result)
        except Exception as exc:
            errors.append({"apr_name": apr_name, "error": str(exc)})
            logger.error(f"rerun_full_apr_extraction_bulk failed for {apr_name}: {exc}")

    return {
        "status": "completed",
        "queued": len(results),
        "failed": len(errors),
        "results": results,
        "errors": errors,
    }


def _reset_and_enqueue_payments(apr_name: str) -> int:
    """Reset extracted payment fields and enqueue extraction jobs. Returns job count."""
    payment_rows = frappe.get_all(
        "APR Payment",
        filters={"parent": apr_name, "parenttype": "Asset Procurement Record"},
        fields=["name", "payment_evidence"],
    )
    jobs = 0
    for row in payment_rows:
        if not row.payment_evidence:
            continue
        frappe.db.set_value("APR Payment", row.name, {
            "extraction_status": "Queued",
            "payment_date": None,
            "amount_paid": None,
            "invoice_reference_in_pdf": None,
            "is_matched": 0,
            "extraction_error": None,
        })
        frappe.db.set_value("APR Payment", row.name, "extraction_status", "Processing")
        frappe.enqueue(
            "mpd_customizations.asset_organizer.ai.apr_extraction.run_payment_extraction",
            queue="long",
            apr_name=apr_name,
            payment_row_name=row.name,
        )
        jobs += 1
        logger.info(f"APR {apr_name}: enqueued payment extraction for {row.name}")

    if jobs:
        from mpd_customizations.asset_organizer.ai.apr_extraction import _recompute_payment_totals
        _recompute_payment_totals(apr_name)

    frappe.db.commit()
    return jobs


@frappe.whitelist()
def rerun_apr_payment_extraction(apr_name: str) -> dict:
    """
    Re-extract all payment rows with bank evidence attached.
    Does not modify uploads, evidence, or item lines.
    """
    _check_rerun_permission()

    if not frappe.db.exists("Asset Procurement Record", apr_name):
        frappe.throw(_("Asset Procurement Record {0} not found").format(apr_name))

    jobs_queued = _reset_and_enqueue_payments(apr_name)
    logger.info(
        f"rerun_apr_payment_extraction: APR={apr_name} jobs={jobs_queued} "
        f"by {frappe.session.user}"
    )
    return {"status": "queued", "apr_name": apr_name, "payment_jobs": jobs_queued}


@frappe.whitelist()
def rerun_apr_payment_extraction_bulk(apr_names) -> dict:
    """Bulk payment re-extraction for multiple APRs."""
    _check_rerun_permission()
    names = _parse_apr_names(apr_names)
    results = []
    errors = []

    for apr_name in names:
        try:
            result = rerun_apr_payment_extraction(apr_name)
            results.append(result)
        except Exception as exc:
            errors.append({"apr_name": apr_name, "error": str(exc)})
            logger.error(f"rerun_apr_payment_extraction_bulk failed for {apr_name}: {exc}")

    return {
        "status": "completed",
        "queued": len(results),
        "failed": len(errors),
        "results": results,
        "errors": errors,
    }


@frappe.whitelist()
def get_apr_summary(apr_name: str) -> dict:
    """
    Return a dashboard summary dict for the given APR.
    Used by the form's client script dashboard indicator.
    """
    apr = frappe.db.get_value(
        "Asset Procurement Record",
        apr_name,
        [
            "record_status",
            "outstanding_balance",
            "total_amount_paid",
            "invoice_total_value",
            "supplier_link",
            "supplier_doctype",
            "supplier_name_raw",
        ],
        as_dict=True,
    )
    if not apr:
        frappe.throw(_("Asset Procurement Record {0} not found").format(apr_name))

    evidence_rows = frappe.db.get_all(
        "APR Evidence Document",
        filters={"parent": apr_name},
        fields=["detected_category", "extraction_status"],
    )

    category_counts: dict[str, int] = {}
    for row in evidence_rows:
        cat = row.detected_category or "Unknown"
        category_counts[cat] = category_counts.get(cat, 0) + 1

    def _has_extracted(cat: str) -> bool:
        return any(
            r.detected_category == cat and r.extraction_status == "Extracted"
            for r in evidence_rows
        )

    checklist = {
        "quote":   _has_extracted("Quote"),
        "po":      _has_extracted("PO"),
        "invoice": _has_extracted("Invoice"),
        "igp":     _has_extracted("IGP"),
    }

    return {
        "record_status":      apr.record_status,
        "outstanding_balance": apr.outstanding_balance,
        "total_amount_paid":  apr.total_amount_paid,
        "invoice_total_value": apr.invoice_total_value,
        "supplier_link":      apr.supplier_link,
        "supplier_doctype":   apr.supplier_doctype,
        "supplier_name_raw":  apr.supplier_name_raw,
        "evidence_by_category": category_counts,
        "checklist":          checklist,
    }

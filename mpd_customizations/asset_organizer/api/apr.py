import frappe
from frappe import _

logger = frappe.logger("asset_organizer")

_ALLOWED_REQUEUE_ROLES = {"System Manager", "Stock Manager"}


@frappe.whitelist()
def requeue_evidence_extraction(evidence_row_name: str) -> dict:
    """
    Reset an evidence row to Queued and re-enqueue background extraction.
    Requires System Manager or Stock Manager role.
    """
    user_roles = set(frappe.get_roles(frappe.session.user))
    if not (user_roles & _ALLOWED_REQUEUE_ROLES):
        frappe.throw(_("Only System Manager or Stock Manager may requeue extractions."), frappe.PermissionError)

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
    )
    logger.info(f"requeue_evidence_extraction: APR={apr_name} row={evidence_row_name} by {frappe.session.user}")
    return {"status": "queued"}


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

    # Evidence counts per category
    evidence_rows = frappe.db.get_all(
        "APR Evidence Document",
        filters={"parent": apr_name},
        fields=["detected_category", "extraction_status"],
    )

    category_counts: dict[str, int] = {}
    for row in evidence_rows:
        cat = row.detected_category or "Unknown"
        category_counts[cat] = category_counts.get(cat, 0) + 1

    # State machine readiness checklist
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

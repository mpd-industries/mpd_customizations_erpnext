import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime

logger = frappe.logger("asset_organizer")


class AssetProcurementRecord(Document):

    # ------------------------------------------------------------------
    # validate — runs on every save (UI or background)
    # ------------------------------------------------------------------

    def validate(self):
        self._compute_payment_totals()
        self._compute_current_location()
        self._check_commissioned_gate()

    def _compute_payment_totals(self):
        """Recompute total_amount_paid and outstanding_balance from child rows."""
        total_paid = sum(
            row.amount_paid or 0
            for row in self.payments
            if row.extraction_status == "Extracted"
        )
        self.total_amount_paid = total_paid
        self.outstanding_balance = (self.invoice_total_value or 0) - total_paid

    def _compute_current_location(self):
        """Set current_location to the most recent APR Location Log entry."""
        if not self.location_log:
            return
        latest = sorted(
            self.location_log,
            key=lambda r: r.log_date or "",
            reverse=True,
        )[0]
        self.current_location = latest.location

    def _check_commissioned_gate(self):
        """Enforce prerequisites before allowing Asset Commissioned status."""
        if self.installation_status == "Commissioned":
            if not self.installation_date:
                frappe.throw(
                    "Installation Date is required to commission this asset."
                )
            if not self.current_location:
                frappe.throw(
                    "Current Location must be logged before commissioning. "
                    "Add a Location Log entry."
                )
            self.record_status = "Asset Commissioned"

    # ------------------------------------------------------------------
    # on_update — enqueue extraction for newly added files
    # ------------------------------------------------------------------

    def on_update(self):
        self._enqueue_new_upload_rows()
        self._enqueue_new_payment_rows()

    def _enqueue_new_upload_rows(self):
        """Enqueue background segmentation for any newly uploaded document."""
        for row in self.uploaded_documents:
            if row.upload_status == "Queued" and row.upload_file:
                frappe.db.set_value(
                    "Asset Documentation", row.name, "upload_status", "Processing"
                )
                frappe.enqueue(
                    "mpd_customizations.asset_organizer.ai.apr_extraction.run_segmentation_job",
                    queue="long",
                    apr_name=self.name,
                    upload_row_name=row.name,
                )
                logger.info(
                    f"APR {self.name}: enqueued segmentation for upload row {row.name}"
                )

    def _enqueue_new_payment_rows(self):
        """Enqueue payment extraction for any payment row with a new file."""
        for row in self.payments:
            if row.extraction_status == "Queued" and row.payment_evidence:
                frappe.db.set_value(
                    "APR Payment", row.name, "extraction_status", "Processing"
                )
                frappe.enqueue(
                    "mpd_customizations.asset_organizer.ai.apr_extraction.run_payment_extraction",
                    queue="long",
                    apr_name=self.name,
                    payment_row_name=row.name,
                )
                logger.info(
                    f"APR {self.name}: enqueued payment extraction for row {row.name}"
                )

    # ------------------------------------------------------------------
    # before_insert — auto-set log_date and logged_by on location rows
    # ------------------------------------------------------------------

    def before_insert(self):
        self._stamp_location_log_rows()

    def before_save(self):
        self._stamp_location_log_rows()

    def _stamp_location_log_rows(self):
        for row in self.location_log:
            if not row.log_date:
                row.log_date = now_datetime()
            if not row.logged_by:
                row.logged_by = frappe.session.user

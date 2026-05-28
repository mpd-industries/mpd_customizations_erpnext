// Client script for Asset Procurement Record
// Handles: status indicator, AI description prompt, extraction actions

const APR_EXTRACTION_ROLES = ["System Manager", "Stock Manager"];

frappe.ui.form.on("Asset Procurement Record", {

    refresh(frm) {
        _set_status_indicator(frm);
        _show_ai_description_prompt(frm);
        _add_extraction_buttons(frm);
    },

    record_status(frm) {
        _set_status_indicator(frm);
    },

    ai_description_suggestion(frm) {
        _show_ai_description_prompt(frm);
    },
});

// ---------------------------------------------------------------------------
// Status indicator
// ---------------------------------------------------------------------------

const STATUS_COLOURS = {
    "Draft":                "grey",
    "Quotation Captured":   "blue",
    "PO Raised":            "blue",
    "Invoiced":             "orange",
    "Goods on Site":        "orange",
    "Payment Pending":      "orange",
    "Partially Paid":       "orange",
    "Fully Settled":        "green",
    "Insurance Ready":      "green",
    "Asset Commissioned":   "green",
};

function _set_status_indicator(frm) {
    const status = frm.doc.record_status;
    if (!status) return;
    const colour = STATUS_COLOURS[status] || "grey";
    frm.page.set_indicator(status, colour);
}

// ---------------------------------------------------------------------------
// AI description suggestion prompt
// ---------------------------------------------------------------------------

function _show_ai_description_prompt(frm) {
    const suggestion = frm.doc.ai_description_suggestion;
    const current_desc = frm.doc.asset_description;

    if (!suggestion || current_desc) return;

    frappe.msgprint({
        title: __("AI Suggested Description"),
        message: __(
            "AI suggested: <strong>{0}</strong><br><br>"
            + "Click <strong>Accept</strong> to use this suggestion, "
            + "or type your own description in the Asset Description field.",
            [suggestion]
        ),
        primary_action: {
            label: __("Accept"),
            action() {
                frappe.model.set_value(frm.doctype, frm.docname, "asset_description", suggestion);
                this.hide();
            },
        },
    });
}

// ---------------------------------------------------------------------------
// Extraction actions (form)
// ---------------------------------------------------------------------------

function _user_can_run_extraction() {
    return APR_EXTRACTION_ROLES.some((role) => frappe.user_roles.includes(role));
}

function _add_extraction_buttons(frm) {
    if (frm.is_new() || frm.doc.docstatus === 2) return;
    if (!_user_can_run_extraction()) return;

    frm.add_custom_button(__("Run Entire Extraction"), () => {
        frappe.confirm(
            __(
                "This will clear all extracted evidence, item lines, and document-derived "
                + "fields on this APR, then re-segment and re-extract all uploaded PDFs in order. "
                + "Payment rows are not changed.<br><br>Continue?"
            ),
            () => _call_extraction_api(frm, "rerun_full_apr_extraction"),
            () => {}
        );
    }, __("Actions"));

    frm.add_custom_button(__("Re-extract Payments"), () => {
        frappe.confirm(
            __(
                "This will clear extracted payment fields and re-run bank advice extraction "
                + "for all payment rows with files attached. Evidence and uploads are not changed."
                + "<br><br>Continue?"
            ),
            () => _call_extraction_api(frm, "rerun_apr_payment_extraction"),
            () => {}
        );
    }, __("Actions"));
}

function _call_extraction_api(frm, method) {
    frappe.call({
        method: `mpd_customizations.asset_organizer.api.apr.${method}`,
        args: { apr_name: frm.doc.name },
        freeze: true,
        freeze_message: __("Queuing extraction jobs..."),
        callback(r) {
            if (r.exc) return;
            const data = r.message || {};
            let msg = __("Jobs queued.");
            if (data.segmentation_jobs != null) {
                msg = __("Queued {0} segmentation job(s).", [data.segmentation_jobs]);
            } else if (data.payment_jobs != null) {
                msg = __("Queued {0} payment extraction job(s).", [data.payment_jobs]);
            }
            frappe.show_alert({ message: msg, indicator: "green" });
            frm.reload_doc();
        },
    });
}

// ---------------------------------------------------------------------------
// List view bulk actions
// ---------------------------------------------------------------------------

frappe.listview_settings["Asset Procurement Record"] = {
    onload(listview) {
        if (!_user_can_run_extraction()) return;

        listview.page.add_actions_menu_item(__("Run Entire Extraction"), () => {
            _bulk_extraction_action(
                listview,
                "rerun_full_apr_extraction_bulk",
                __(
                    "Reset and re-extract document evidence for {0} selected APR(s)? "
                    + "Payment rows will not be changed."
                )
            );
        });

        listview.page.add_actions_menu_item(__("Re-extract Payments"), () => {
            _bulk_extraction_action(
                listview,
                "rerun_apr_payment_extraction_bulk",
                __(
                    "Re-extract payments for {0} selected APR(s)? "
                    + "Evidence and uploads will not be changed."
                )
            );
        });
    },
};

function _bulk_extraction_action(listview, method, message_template) {
    const names = listview.get_checked_items(true);
    if (!names.length) {
        frappe.msgprint(__("Please select at least one Asset Procurement Record."));
        return;
    }

    frappe.confirm(
        message_template.replace("{0}", names.length),
        () => {
            frappe.call({
                method: `mpd_customizations.asset_organizer.api.apr.${method}`,
                args: { apr_names: names },
                freeze: true,
                freeze_message: __("Queuing jobs..."),
                callback(r) {
                    if (r.exc) return;
                    const data = r.message || {};
                    const queued = data.queued || 0;
                    const failed = data.failed || 0;
                    let msg = __("Queued {0} record(s).", [queued]);
                    if (failed) {
                        msg += " " + __("Failed: {0}.", [failed]);
                    }
                    frappe.show_alert({ message: msg, indicator: failed ? "orange" : "green" });
                    listview.clear_checked_items();
                    listview.refresh();
                },
            });
        },
        () => {
            listview.clear_checked_items();
        }
    );
}

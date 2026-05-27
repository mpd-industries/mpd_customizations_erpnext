// Client script for Asset Procurement Record
// Handles: status indicator colours + AI description suggestion prompt

frappe.ui.form.on("Asset Procurement Record", {

    refresh(frm) {
        _set_status_indicator(frm);
        _show_ai_description_prompt(frm);
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
            action(values) {
                frappe.model.set_value(frm.doctype, frm.docname, "asset_description", suggestion);
                this.hide();
            },
        },
    });
}

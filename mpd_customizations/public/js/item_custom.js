// Intercept frappe.new_doc for Item before quick entry dialog appears.
// This handles both the list New button and linked field Create buttons.
const _original_new_doc = frappe.new_doc.bind(frappe);
frappe.new_doc = function(doctype, ...args) {
    if (doctype === 'Item') {
        frappe.set_route('Form', 'Item Request', 'new-item-request-1');
        return;
    }
    return _original_new_doc(doctype, ...args);
};

// Belt and suspenders — if someone navigates directly to a new Item URL
frappe.ui.form.on('Item', {
    onload(frm) {
        if (frm.is_new()) {
            frappe.set_route('Form', 'Item Request', 'new-item-request-1');
        }
    },
});
frappe.ui.form.on('Item', {
    refresh: function(frm) {
        if (frm.is_new()) {
            frm.set_value('description', 'Default description from code!');
        }
        frappe.msgprint(__("Custom Logic Loaded from App"));
    }
});
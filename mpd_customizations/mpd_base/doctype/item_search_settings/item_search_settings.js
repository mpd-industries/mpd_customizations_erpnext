frappe.ui.form.on('Item Search Settings', {
    refresh(frm) {
        frm.add_custom_button('Rebuild Search Index', () => {
            frappe.confirm(
                'This will rebuild the item similarity index from all active items. Continue?',
                () => {
                    frappe.call({
                        method: 'mpd_customizations.mpd_base.item_ai.dedup.rebuild_search_index',
                        callback(r) {
                            frm.reload_doc();
                        },
                    });
                }
            );
        });
    },
});
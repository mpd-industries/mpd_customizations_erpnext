frappe.ui.form.on('OTH Reclassification', {

    refresh(frm) {
        if (frm._poll_timer) {
            clearInterval(frm._poll_timer);
            frm._poll_timer = null;
        }
        if (frm.doc.status === 'Analyzing') {
            _poll_for_completion(frm);
        }
        _render_banner(frm);
        _render_buttons(frm);
    },

});


// ─── Status banner ────────────────────────────────────────────────────────────

function _render_banner(frm) {
    const map = {
        'Draft':     ['blue',   'Create the document, then click <b>Load OTH Items</b> to fetch all OTH-prefixed items.'],
        'Analyzing': ['yellow', 'AI analysis is running in the background. This page will refresh automatically.'],
        'Reviewed':  ['green',  'AI suggestions are ready. Review the tables below, change any action to Skip, then click <b>Apply Selected</b>.'],
        'Applied':   ['green',  'All selected suggestions have been applied. Items have been renamed.'],
    };
    const [indicator, message] = map[frm.doc.status] || ['blue', ''];
    if (message) {
        frm.dashboard.set_headline_alert(
            `<span class="indicator ${indicator}">${message}</span>`
        );
    }
}


// ─── Buttons ──────────────────────────────────────────────────────────────────

function _render_buttons(frm) {
    frm.clear_custom_buttons();

    if (frm.doc.status === 'Draft' || frm.doc.status === 'Reviewed') {
        frm.add_custom_button('Load OTH Items', () => _load_items(frm));
    }

    if (frm.doc.status === 'Draft' && frm.doc.items && frm.doc.items.length > 0) {
        frm.add_custom_button('Analyze with AI', () => _analyze(frm), 'Actions');
    }

    if (frm.doc.status === 'Reviewed') {
        frm.add_custom_button('Analyze with AI', () => _analyze(frm), 'Actions');
        frm.add_custom_button(
            'Apply Selected',
            () => _apply(frm),
            'Actions',
        );
    }
}


// ─── Load OTH Items ───────────────────────────────────────────────────────────

function _load_items(frm) {
    const do_load = () => {
        frappe.show_alert({ message: 'Loading OTH items…', indicator: 'blue' });
        frappe.call({
            method: 'mpd_customizations.mpd_base.oth_review.review.load_oth_items',
            args: { doc_name: frm.doc.name },
            callback(r) {
                if (r.message) {
                    frm.reload_doc().then(() => {
                        frappe.show_alert({
                            message: `Loaded ${r.message.loaded} OTH items.`,
                            indicator: 'green',
                        });
                    });
                }
            },
        });
    };

    if (frm.is_new()) {
        if (!frm.doc.title) {
            frappe.msgprint('Please enter a title before loading items.');
            return;
        }
        frm.save().then(do_load);
    } else {
        do_load();
    }
}


// ─── Analyze ──────────────────────────────────────────────────────────────────

function _analyze(frm) {
    if (!frm.doc.items || frm.doc.items.length === 0) {
        frappe.msgprint('No items loaded. Click Load OTH Items first.');
        return;
    }

    frappe.confirm(
        `Send ${frm.doc.items.length} OTH items to the AI for reclassification?<br><br>
        This will run in the background and may take a minute.`,
        () => {
            frappe.call({
                method: 'mpd_customizations.mpd_base.oth_review.review.enqueue_oth_review',
                args: { doc_name: frm.doc.name },
                callback(r) {
                    if (r.message && r.message.status === 'queued') {
                        frm.reload_doc().then(() => {
                            frappe.show_alert({
                                message: 'Analysis queued — this page will update when complete.',
                                indicator: 'blue',
                            });
                            _poll_for_completion(frm);
                        });
                    }
                },
            });
        }
    );
}


// ─── Polling ──────────────────────────────────────────────────────────────────

function _poll_for_completion(frm) {
    if (frm._poll_timer) clearInterval(frm._poll_timer);

    frm._poll_timer = setInterval(() => {
        frappe.db.get_value('OTH Reclassification', frm.doc.name, 'status')
            .then(r => {
                const status = r.message && r.message.status;
                if (status && status !== 'Analyzing') {
                    clearInterval(frm._poll_timer);
                    frm._poll_timer = null;
                    frm.reload_doc();
                }
            });
    }, 4000);
}


// ─── Apply ────────────────────────────────────────────────────────────────────

function _apply(frm) {
    const to_apply    = (frm.doc.suggestions    || []).filter(r => r.action === 'Apply').length;
    const to_create_p = (frm.doc.new_prefixes   || []).filter(r => r.action === 'Create').length;
    const to_create_g = (frm.doc.new_item_groups || []).filter(r => r.action === 'Create').length;

    if (to_apply + to_create_p + to_create_g === 0) {
        frappe.msgprint('Nothing to apply — all rows are set to Skip.');
        return;
    }

    let msg = `This will:<ul>`;
    if (to_create_g) msg += `<li>Create <b>${to_create_g}</b> new Item Group(s)</li>`;
    if (to_create_p) msg += `<li>Create <b>${to_create_p}</b> new Item Category Code(s)</li>`;
    if (to_apply)    msg += `<li>Rename <b>${to_apply}</b> item(s) and update their group/name</li>`;
    msg += `</ul>This cannot be undone easily. Proceed?`;

    frappe.confirm(msg, () => {
        frappe.show_alert({ message: 'Applying suggestions…', indicator: 'blue' });
        frappe.call({
            method: 'mpd_customizations.mpd_base.oth_review.review.apply_suggestions',
            args: { doc_name: frm.doc.name },
            callback(r) {
                const res = r.message || {};
                frm.reload_doc().then(() => {
                    let summary = `Done! `;
                    if (res.groups_created)   summary += `${res.groups_created} group(s) created. `;
                    if (res.prefixes_created) summary += `${res.prefixes_created} prefix(es) created. `;
                    if (res.items_renamed)    summary += `${res.items_renamed} item(s) renamed. `;
                    if (res.rename_errors && res.rename_errors.length) {
                        summary += `${res.rename_errors.length} rename error(s) — see Error Log.`;
                        frappe.msgprint({
                            title: 'Applied with Errors',
                            message: summary,
                            indicator: 'orange',
                        });
                    } else {
                        frappe.show_alert({ message: summary, indicator: 'green' });
                    }
                });
            },
        });
    });
}

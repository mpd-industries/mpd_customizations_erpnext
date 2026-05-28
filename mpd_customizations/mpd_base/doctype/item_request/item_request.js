frappe.ui.form.on('Item Request', {

    refresh(frm) {
        if (frm._ai_poll_timer) {
            clearInterval(frm._ai_poll_timer);
            frm._ai_poll_timer = null;
        }
        if (frm.doc.status === 'Pending AI Review') {
            poll_for_status_change(frm);
        }
        render_status_banner(frm);
        render_action_buttons(frm);
        style_inline_buttons(frm);
    },

    // Inline form buttons (Button fieldtype)
    check_similar_items_btn(frm) { run_dedup_check(frm); },
    generate_ai_btn(frm)         { generate_ai_suggestion(frm); },
    create_item_btn(frm)         { create_item(frm); },

    // Reset dedup when key input fields change
    requester_description(frm) { reset_dedup_if_needed(frm); },
    tally_name(frm)            { reset_dedup_if_needed(frm); },
    tally_alias(frm)           { reset_dedup_if_needed(frm); },
    legacy_material_code(frm)  { reset_dedup_if_needed(frm); },

    // AI suggestion fields — flag for MA review if a non-MA user edits them
    ai_item_name_suggestion(frm)      { flag_for_ma_if_needed(frm); },
    ai_prefix_suggestion(frm)         { flag_for_ma_if_needed(frm); },
    ai_sub_category_suggestion(frm)   { flag_for_ma_if_needed(frm); },
    ai_item_group_suggestion(frm)     { flag_for_ma_if_needed(frm); },
    ai_asset_category_suggestion(frm) { flag_for_ma_if_needed(frm); },
    ai_solids_suffix_suggestion(frm)  { flag_for_ma_if_needed(frm); },
    ai_hsn_suggestion(frm)            { flag_for_ma_if_needed(frm); },
    ai_uom_suggestion(frm)            { flag_for_ma_if_needed(frm); },

});


// ─── Helpers ──────────────────────────────────────────────────────────────────

function is_ma() {
    return frappe.user_roles.includes('Master Approver') ||
           frappe.user_roles.includes('System Manager');
}

function style_inline_buttons(frm) {
    const style = (fieldname, cls, css) => {
        const field = frm.fields_dict[fieldname];
        if (!field || !field.$input) return;
        field.$input
            .removeClass('btn-default btn-primary btn-success')
            .addClass(cls)
            .css(css);
    };

    style('check_similar_items_btn', 'btn-primary', {
        'padding': '8px 24px',
        'font-size': '14px',
        'font-weight': '600',
    });
    style('generate_ai_btn', 'btn-primary', {
        'padding': '8px 24px',
        'font-size': '14px',
        'font-weight': '600',
    });
    style('create_item_btn', 'btn-success', {
        'padding': '10px 36px',
        'font-size': '16px',
        'font-weight': '700',
        'letter-spacing': '0.3px',
        'margin-bottom': '12px',
    });
}

function reload_and_render(frm) {
    // reload_doc fetches the latest doc and calls frm.refresh() internally,
    // which triggers our refresh event handler (render_status_banner + render_action_buttons).
    return frm.reload_doc();
}


// ─── Status banner ────────────────────────────────────────────────────────────

function render_status_banner(frm) {
    const map = {
        'Draft':               ['blue',   'Fill in the details on the left, then click Check for Similar Items below.'],
        'Pending Dedup Check': ['yellow', 'Checking for similar items...'],
        'Dedup Confirmed':     ['blue',   'No duplicates found (or acknowledged). Click Generate AI Suggestion below.'],
        'Pending AI Review':   ['yellow', 'AI review in progress...'],
        'AI Reviewed':         ['green',  'AI suggestion is ready below. Review the fields — edit any to send for MA approval, or click  <b>Create Item</b>  to accept as-is.'],
        'Duplicate Flagged':   ['red',    'AI flagged a possible duplicate. A Master Approver will review and resolve.'],
        'Pending MA Approval': ['orange', 'The suggestion was modified — awaiting Master Approver review.'],
        'Approved':            ['green',  `Approved. Item created: ${frm.doc.created_item_code || '—'}`],
        'Rejected':            ['red',    'Request rejected. See the MA Review Note in the Approval section.'],
    };
    const [indicator, message] = map[frm.doc.status] || ['blue', ''];
    if (message) {
        frm.dashboard.set_headline_alert(
            `<span class="indicator ${indicator}">${message}</span>`
        );
    }
}


// ─── Action buttons (top toolbar — MA actions only) ───────────────────────────

function render_action_buttons(frm) {
    frm.clear_custom_buttons();
    const s = frm.doc.status;

    // MA approval path
    if (is_ma() && ['Pending MA Approval', 'Duplicate Flagged'].includes(s)) {
        frm.add_custom_button('Approve & Create Item', () => approve_request(frm), 'Actions');
        frm.add_custom_button('Reject', () => reject_request(frm), 'Actions');
    }
}


// ─── Flag for MA review when AI fields are edited ─────────────────────────────

function flag_for_ma_if_needed(frm) {
    if (frm.doc.status !== 'AI Reviewed') return;
    if (is_ma()) return;  // MAs can freely edit without escalating
    if (frm.is_new()) return;

    frappe.call({
        method: 'mpd_customizations.mpd_base.item_ai.review.flag_for_ma_approval',
        args: { request_name: frm.doc.name },
        callback(r) {
            if (r.message && r.message.status === 'flagged') {
                reload_and_render(frm).then(() => {
                    frappe.show_alert({
                        message: 'You edited the AI suggestion — sent for Master Approver review.',
                        indicator: 'orange',
                    });
                });
            }
        },
    });
}


// ─── Dedup ────────────────────────────────────────────────────────────────────

function reset_dedup_if_needed(frm) {
    if (!frm.doc.dedup_check_done) return;
    if (frm.is_new()) return;
    frappe.call({
        method: 'mpd_customizations.mpd_base.item_ai.dedup.reset_dedup',
        args: { request_name: frm.doc.name },
        callback() {
            $('.dedup-results-box').remove();
            reload_and_render(frm).then(() => {
                frappe.show_alert({
                    message: 'Details changed — please re-check for similar items.',
                    indicator: 'orange',
                });
            });
        },
    });
}


function run_dedup_check(frm) {
    if (!frm.doc.requester_description) {
        frappe.msgprint('Please enter a description before checking.');
        return;
    }

    const do_check = () => {
        frappe.call({
            method: 'mpd_customizations.mpd_base.item_ai.dedup.check_item_duplicates_and_set_status',
            args: {
                request_name:         frm.doc.name,
                description:          frm.doc.requester_description,
                tally_name:           frm.doc.tally_name           || null,
                tally_alias:          frm.doc.tally_alias          || null,
                legacy_material_code: frm.doc.legacy_material_code || null,
                hsn_code:             frm.doc.gst_hsn_code           || null,
            },
            callback(r) {
                const candidates = r.message || [];
                reload_and_render(frm).then(() => {
                    if (candidates.length === 0) {
                        frappe.show_alert({
                            message: 'No similar items found — click Generate AI Suggestion.',
                            indicator: 'green',
                        });
                    } else {
                        show_dedup_results(frm, candidates);
                    }
                });
            },
        });
    };

    if (frm.is_new()) {
        frm.save().then(do_check);
    } else {
        do_check();
    }
}


function show_dedup_results(frm, candidates) {
    $('.dedup-results-box').remove();

    const container = $(frm.fields_dict['check_similar_items_btn'].wrapper)
        .closest('.form-section');

    const rows = candidates.map(c => `
        <tr>
            <td>
                <a href="/app/item/${encodeURIComponent(c.name)}"
                   target="_blank">${c.name}</a>
            </td>
            <td>${c.item_name  || ''}</td>
            <td>${c.item_group || ''}</td>
            <td>${c.tally_name || ''}</td>
        </tr>
    `).join('');

    container.after(`
        <div class="dedup-results-box"
             style="margin:10px 15px; border:1px solid #ffc107;
                    border-radius:6px; padding:16px; background:#fffbf0">
            <p style="font-weight:600; margin-bottom:10px">
                ⚠ These items may already exist — review before continuing:
            </p>
            <table class="table table-bordered table-condensed"
                   style="margin-bottom:14px">
                <thead>
                    <tr>
                        <th>Item Code</th>
                        <th>Item Name</th>
                        <th>Item Group</th>
                        <th>Tally Name</th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
            <button class="btn btn-warning btn-sm dedup-confirm-btn">
                I acknowledge — my item is different from all of the above
            </button>
        </div>
    `);

    $('.dedup-confirm-btn').one('click', () => confirm_dedup(frm));
}


function confirm_dedup(frm) {
    frappe.call({
        method: 'mpd_customizations.mpd_base.item_ai.dedup.confirm_dedup',
        args: { request_name: frm.doc.name },
        callback() {
            $('.dedup-results-box').remove();
            reload_and_render(frm).then(() => {
                frappe.show_alert({
                    message: 'Acknowledged — click Generate AI Suggestion.',
                    indicator: 'green',
                });
            });
        },
    });
}


// ─── AI generation ────────────────────────────────────────────────────────────

function generate_ai_suggestion(frm) {
    const do_generate = () => {
        frappe.call({
            method: 'mpd_customizations.mpd_base.item_ai.review.enqueue_item_ai_review',
            args: { request_name: frm.doc.name },
            callback() {
                reload_and_render(frm).then(() => {
                    frappe.show_alert({
                        message: 'AI review queued — checking progress...',
                        indicator: 'blue',
                    });
                    poll_for_status_change(frm);
                });
            },
        });
    };

    if (frm.is_dirty()) {
        frm.save().then(do_generate);
    } else {
        do_generate();
    }
}


function poll_for_status_change(frm, interval_ms=4000, max_attempts=30) {
    let attempts = 0;

    frm._ai_poll_timer = setInterval(() => {
        attempts++;

        frappe.call({
            method: 'frappe.client.get_value',
            args: {
                doctype:   'Item Request',
                filters:   { name: frm.doc.name },
                fieldname: 'status',
            },
            callback(r) {
                if (!r.message) return;
                const status = r.message.status;

                if (status === 'Pending AI Review') {
                    frm.dashboard.set_headline_alert(
                        `<span class="indicator yellow">
                            AI review in progress... (${attempts * interval_ms / 1000}s)
                        </span>`
                    );
                    return;
                }

                clearInterval(frm._ai_poll_timer);
                frm._ai_poll_timer = null;

                reload_and_render(frm).then(() => {
                    frappe.show_alert({
                        message: `AI review complete — ${status}`,
                        indicator: status === 'AI Reviewed' ? 'green' : 'orange',
                    });
                });
            },
        });

        if (attempts >= max_attempts) {
            clearInterval(frm._ai_poll_timer);
            frm._ai_poll_timer = null;
            frappe.show_alert({
                message: 'AI review is taking longer than expected — refresh manually.',
                indicator: 'orange',
            });
        }

    }, interval_ms);
}


// ─── Item creation (requester accepts AI result as-is) ────────────────────────

function create_item(frm) {
    frappe.confirm(
        'Create the item with the AI suggested values?',
        () => {
            const do_create = () => {
                frappe.call({
                    method: 'mpd_customizations.mpd_base.item_ai.review.create_item_from_request',
                    args: { request_name: frm.doc.name },
                    callback(r) {
                        reload_and_render(frm).then(() => {
                            if (r.message) {
                                frappe.show_alert({
                                    message: `Item created: ${r.message}`,
                                    indicator: 'green',
                                });
                            }
                        });
                    },
                });
            };

            if (frm.is_dirty()) {
                frm.save().then(do_create);
            } else {
                do_create();
            }
        }
    );
}


// ─── MA approval / rejection ──────────────────────────────────────────────────

function approve_request(frm) {
    frappe.confirm(
        'Approve this request and create the item with the current field values?',
        () => {
            frappe.call({
                method: 'mpd_customizations.mpd_base.item_ai.review.approve_request',
                args: { request_name: frm.doc.name },
                callback(r) {
                    reload_and_render(frm).then(() => {
                        if (r.message) {
                            frappe.show_alert({
                                message: `Approved — item created: ${r.message}`,
                                indicator: 'green',
                            });
                        }
                    });
                },
            });
        }
    );
}

function reject_request(frm) {
    frappe.prompt(
        {
            label: 'Reason for rejection',
            fieldname: 'review_note',
            fieldtype: 'Small Text',
            reqd: 1,
        },
        ({ review_note }) => {
            frappe.call({
                method: 'mpd_customizations.mpd_base.item_ai.review.reject_request',
                args: { request_name: frm.doc.name, review_note },
                callback() {
                    reload_and_render(frm).then(() => {
                        frappe.show_alert({
                            message: 'Request rejected.',
                            indicator: 'red',
                        });
                    });
                },
            });
        },
        'Reject Item Request',
        'Reject'
    );
}

// Pricing Request — status, confirmed price, and approved cost breakdown when available.

frappe.ui.form.on("Pricing Request", {
	onload(frm) {
		if (frm.doc.__islocal && frm.doc.product) {
			_fetch_solids(frm);
		}
	},

	refresh(frm) {
		_set_customer_product_query(frm);
		_render_pr_actions(frm);
		_render_pr_cost_summary(frm);

		if (!_is_sales_view()) {
			// Costing team: show link to the Pricing Calculation
			if (!frm.is_new() && frm.doc.pricing_calculation) {
				frm.add_custom_button(__("Open Pricing Calculation"), () => {
					frappe.set_route("Form", "Pricing Calculation", frm.doc.pricing_calculation);
				});

			}
		}
	},

	product(frm) {
		_fetch_solids(frm);
	},

	customer_product(frm) {
		_fetch_solids_from_customer_product(frm);
	},
});

function _set_customer_product_query(frm) {
	frm.set_query("customer_product", () => ({
		filters: { status: "Approved", is_active: 1 },
	}));
}

function _is_sales_view() {
	return !frappe.user.has_role("Costing Approver") &&
		!frappe.user.has_role("Costing User") &&
		!frappe.user.has_role("System Manager");
}

function _fetch_solids(frm) {
	if (!frm.doc.product && !frm.doc.customer_product) return;
	if (frm.doc.product) {

		frappe.db.get_value("Item", frm.doc.product, "custom_solids_content_pct").then(r => {
			if (r.message && r.message.custom_solids_content_pct) {
				frm.set_value("solids_content_pct", r.message.custom_solids_content_pct);
			}
		});
	}
	if (frm.doc.customer_product) {
		_fetch_solids_from_customer_product(frm);
	}
}

function _fetch_solids_from_customer_product(frm) {
    if (!frm.doc.customer_product) return;

    frappe.db.get_doc("Customer Product", frm.doc.customer_product)
        .then(doc => {
            // Access the child table (adjust field name to match your child table fieldname)
            const formulations = doc.formulations; // ← replace with your actual child table fieldname
            
            if (!formulations || formulations.length === 0) return;

            const firstRow = formulations[0];

            if (!firstRow.item) return;

            frappe.db.get_value("Item", firstRow.item, "custom_solids_content_pct")
                .then(r => {
                    if (r?.message?.custom_solids_content_pct) {
                        frm.set_value("solids_content_pct", r.message.custom_solids_content_pct);
                    }
                });
        });
}


function _render_pr_cost_summary(frm) {
	if (!frm.fields_dict.cost_summary_html) return;

	const $wrapper = frm.fields_dict.cost_summary_html.$wrapper;
	$wrapper.empty();

	if (!frm.doc.cost_summary_json) return;

	let summary = frm.doc.cost_summary_json;
	if (typeof summary === "string") {
		try {
			summary = JSON.parse(summary);
		} catch (e) {
			return;
		}
	}

	const heads = summary.heads || [];
	if (!heads.length) return;

	const title = summary.formulation_id || summary.bom || "";
	const tbody = heads.map(h => {
		if (h.is_total) {
			return `<tr style="background:#e3f2fd;border-top:2px solid #1565c0;">
				<td class="font-weight-bold" style="padding:4px 8px;color:#1565c0;">${frappe.utils.escape_html(h.label)}</td>
				<td class="text-right font-weight-bold" style="padding:4px 8px;color:#1565c0;">₹${(h.amount_per_kg || 0).toFixed(2)}/kg</td>
				<td style="padding:4px 8px;border-left:1px solid #e0e0e0;"></td>
			</tr>`;
		}
		return `<tr>
			<td style="padding:3px 8px;">${frappe.utils.escape_html(h.label)}</td>
			<td class="text-right" style="padding:3px 8px;">₹${(h.amount_per_kg || 0).toFixed(2)}/kg</td>
			<td class="text-right text-muted" style="padding:3px 8px;border-left:1px solid #e0e0e0;">₹${(h.running_total || 0).toFixed(2)}</td>
		</tr>`;
	}).join("");

	$wrapper.html(`
		<div class="border rounded p-3" style="background:#fafafa;">
			<div class="font-weight-bold mb-2" style="font-size:1.05em;">
				━━ ${__("COST BREAKDOWN")}${title ? ` — ${frappe.utils.escape_html(title)}` : ""} ━━
			</div>
			<table class="table table-sm mb-0" style="font-size:12px;">
				<thead>
					<tr style="border-bottom:1px solid #bdbdbd;">
						<th style="padding:3px 8px;min-width:180px;">${__("Component")}</th>
						<th class="text-right" style="padding:3px 8px;width:110px;">${__("Amount/kg")}</th>
						<th class="text-right text-muted" style="padding:3px 8px;width:120px;border-left:1px solid #e0e0e0;">${__("Running Total")}</th>
					</tr>
				</thead>
				<tbody>${tbody}</tbody>
			</table>
		</div>
	`);
}

function _render_pr_actions(frm) {
	const status = frm.doc.status || "Draft";

	// Submit button only when Ready to Quote and not yet submitted
	if (status === "Ready to Quote" && !frm.doc.docstatus) {
		frm.add_custom_button(__("Submit for MD Approval"), () => {
			frm.savesubmit();
		}, __("Actions"));
	}

	// MD approval buttons (post-submit)
	if (status === "Pending Approval" && frm.doc.docstatus === 1 && frappe.user.has_role("Costing Approver")) {
		frm.add_custom_button(__("Approve"), () => {
			frappe.db.set_value("Pricing Request", frm.doc.name, "status", "Approved").then(() => {
				frappe.show_alert({ message: __("Approved"), indicator: "green" });
				frm.reload_doc();
			});
		}, __("Decision"));

		frm.add_custom_button(__("Reject"), () => {
			frappe.prompt(
				{ fieldname: "reason", label: __("Rejection Reason"), fieldtype: "Small Text", reqd: 1 },
				values => {
					frappe.db.set_value("Pricing Request", frm.doc.name, "status", "Rejected").then(() => {
						frappe.show_alert({ message: __("Rejected"), indicator: "red" });
						frm.reload_doc();
					});
				},
				__("Reject Pricing Request"),
				__("Reject")
			);
		}, __("Decision"));
	}
}

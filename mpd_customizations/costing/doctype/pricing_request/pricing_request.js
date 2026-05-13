// Pricing Request — sales-facing form
// Shows only status and final price. No costing details visible here.

frappe.ui.form.on("Pricing Request", {
	onload(frm) {
		if (frm.doc.__islocal && frm.doc.product) {
			_fetch_solids(frm);
		}
	},

	refresh(frm) {
		_render_status_panel(frm);

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
            console.log("First formulation row:", firstRow);

            if (!firstRow.item) return;

            frappe.db.get_value("Item", firstRow.item, "custom_solids_content_pct")
                .then(r => {
                    if (r?.message?.custom_solids_content_pct) {
                        frm.set_value("solids_content_pct", r.message.custom_solids_content_pct);
                    }
                });
        });
}


function _render_status_panel(frm) {
	const status = frm.doc.status || "Draft";
	const price = frm.doc.confirmed_price_per_kg || 0;
	const qty = frm.doc.quantity_kg || 0;
	const total = frm.doc.total_price || (qty * price);
	const priority = frm.doc.priority || "Normal";

	const priority_color = {
		"Urgent": "red",
		"High": "orange",
		"Normal": "blue",
		"Low": "gray",
	}[priority] || "blue";

	frm.dashboard.add_comment(
		`Priority: <strong style="color:${priority_color}">${priority}</strong>`,
		priority_color === "red" ? "red" : "blue",
		true
	);

	const panels = {
		"Draft": ["blue", `📋 Saved — costing team notified. They will gather rates and evaluate formulations.`],
		"Awaiting Rates": ["orange", `⏳ ${__("Rates being gathered")} — purchase team notified. Please wait.`],
		"Ready for Working": ["yellow", `🔄 Previous price available — fresh rates being gathered.${price ? ` Previous: ₹${price.toFixed(2)}/kg` : ""}`],
		"Ready to Quote": ["green", `✓ Price ready: <strong>₹${price.toFixed(2)}/kg</strong>${qty ? ` · Total: <strong>₹${total.toFixed(2)}</strong>` : ""}`],
		"Pending Approval": ["blue", `⏳ Submitted for MD review · ₹${price.toFixed(2)}/kg`],
		"Approved": ["green", `✓ <strong>APPROVED</strong> · ₹${price.toFixed(2)}/kg${qty ? ` · Total ₹${total.toFixed(2)}` : ""}`],
		"Rejected": ["red", `✗ Rejected`],
	};

	const [color, msg] = panels[status] || ["gray", status];
	frm.dashboard.add_comment(msg, color, true);

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

frappe.ui.form.on("Material Rate", {
	refresh(frm) {
		if (frm.doc.docstatus === 0 && !frm.doc.__islocal) {
			frm.dashboard.add_comment(
				__("Draft — fill in supplier, rate, and validity then Submit to activate."),
				"yellow",
				true
			);
		}
		_toggle_rate_fields(frm);
	},

	rate_type(frm) {
		_toggle_rate_fields(frm);
	},

	ex_works_rate(frm) {
		_compute_delivered_rate(frm);
	},

	freight_per_unit(frm) {
		_compute_delivered_rate(frm);
	},

	valid_from(frm) {
		if (!frm.doc.valid_from) return;
		// Auto-fill valid_to to end of that month
		const d = frappe.datetime.str_to_obj(frm.doc.valid_from);
		const lastDay = new Date(d.getFullYear(), d.getMonth() + 1, 0);
		frm.set_value("valid_to", frappe.datetime.obj_to_str(lastDay));
	},
});

function _toggle_rate_fields(frm) {
	const is_ex_works = frm.doc.rate_type === "Ex-Works + Freight";
	frm.toggle_display(["ex_works_rate", "freight_per_unit"], is_ex_works);
	frm.set_df_property("delivered_rate", "read_only", is_ex_works ? 1 : 0);
}

function _compute_delivered_rate(frm) {
	if (frm.doc.rate_type === "Ex-Works + Freight") {
		const total = (frm.doc.ex_works_rate || 0) + (frm.doc.freight_per_unit || 0);
		frm.set_value("delivered_rate", total);
	}
}

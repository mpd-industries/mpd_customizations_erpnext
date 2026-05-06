frappe.ui.form.on("Processing Charge", {
	refresh(frm) {
		_toggle_freight_field(frm);
	},
	includes_outward_freight(frm) {
		_toggle_freight_field(frm);
	},
});

function _toggle_freight_field(frm) {
	frm.toggle_display("fg_freight_per_unit", !frm.doc.includes_outward_freight);
}

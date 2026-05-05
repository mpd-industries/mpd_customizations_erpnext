frappe.ui.form.on('Processing Charge', {
	refresh: function(frm) {
		frm.trigger('includes_outward_freight');
	},
	
	includes_outward_freight: function(frm) {
		frm.toggle_display("fg_freight_per_unit", !frm.doc.includes_outward_freight);
	}
});

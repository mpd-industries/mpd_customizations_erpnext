frappe.ui.form.on("Floor Project", {
	refresh(frm) {
		if (!frm.is_new()) {
			frm.add_custom_button(__("Open Project Manager"), () => {
				frappe.set_route("xfloor-project-manager");
			});
			frm.add_custom_button(__("Export PDF"), () => {
				frappe.utils.print("Floor Project", frm.doc.name, "Floor Project P&L");
			});
		}
	},
});

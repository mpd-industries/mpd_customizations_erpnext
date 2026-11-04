// Copyright (c) 2026, mpdindustries and contributors
// For license information, please see license.txt

frappe.ui.form.on("Kit rates", {
	refresh(frm) {
		frm.disable_save();
		if (frm.has_perm("write")) {
			frm.enable_save();
		} else {
			frm.set_intro(__("Only System Managers can edit kit rates."), "blue");
		}
	},
});

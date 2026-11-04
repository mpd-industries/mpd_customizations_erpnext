// Copyright (c) 2026, mpdindustries and contributors
// For license information, please see license.txt

frappe.ui.form.on("Kit Coverage", {
	refresh(frm) {
		frm.disable_save();
		if (frm.has_perm("write")) {
			frm.enable_save();
		}
	},
});

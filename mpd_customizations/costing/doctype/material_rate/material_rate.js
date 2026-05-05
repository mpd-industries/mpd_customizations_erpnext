frappe.ui.form.on('Material Rate', {
	refresh: function(frm) {
		frm.trigger('rate_type');
		if (!frm.doc.is_active) {
			frm.dashboard.add_comment("warning", "This rate is pending. Fill in supplier, rate, and credit days then check Active to activate.", true);
		}
	},
	
	rate_type: function(frm) {
		const is_ex_works = frm.doc.rate_type === "Ex-Works + Freight";
		frm.toggle_display(["ex_works_rate", "freight_per_unit"], is_ex_works);
		frm.set_df_property("delivered_rate", "read_only", is_ex_works ? 1 : 0);
	},
	
	ex_works_rate: function(frm) {
		frm.trigger('calculate_delivered_rate');
	},
	
	freight_per_unit: function(frm) {
		frm.trigger('calculate_delivered_rate');
	},
	
	calculate_delivered_rate: function(frm) {
		if (frm.doc.rate_type === "Ex-Works + Freight") {
			const total = (flt(frm.doc.ex_works_rate) + flt(frm.doc.freight_per_unit));
			frm.set_value("delivered_rate", total);
		}
	},
	
	valid_from: function(frm) {
		if (frm.doc.valid_from) {
			const dt = new Date(frm.doc.valid_from);
			const now = new Date();
			if (dt.toDateString() === now.toDateString()) {
				// today, add 15 seconds
				now.setSeconds(now.getSeconds() + 15);
				frm.set_value("valid_from", frappe.datetime.obj_to_str(now));
			} else if (dt > now && dt.getHours() === 0 && dt.getMinutes() === 0 && dt.getSeconds() === 0) {
				// If future and time is exactly 00:00:00, keep it. If user changed date, time gets reset to 00:00:00
				// But standard datepicker already sets time to 00:00:00 for new dates if time not specified
			}
		}
	}
});

// Inject custom error handler for RateConflictError
let original_save = frappe.ui.form.Controller.prototype.save;
frappe.ui.form.Controller.prototype.save = function() {
	let me = this;
	let original_error_handler = frappe.request.on_error;
	
	frappe.request.on_error = function(err) {
		if (err && err.exc_type === "RateConflictError") {
			const info = err.server_messages ? JSON.parse(err.server_messages)[0] : "Conflict detected.";
			frappe.confirm(
				"An active rate for this item from this supplier in this city already exists. Expire it and save this new rate?",
				function() {
					me.frm.doc.__run_link_triggers = false;
					me.frm.doc.flags = me.frm.doc.flags || {};
					me.frm.doc.flags.auto_expire_confirmed = true;
					me.save();
				}
			);
			return false; // Prevent default error message
		}
		if (original_error_handler) {
			return original_error_handler(err);
		}
	};
	
	let ret = original_save.apply(this, arguments);
	
	// Restore after a short delay
	setTimeout(() => {
		frappe.request.on_error = original_error_handler;
	}, 1000);
	
	return ret;
};

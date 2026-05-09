let _cfg_financing_rate = null;
let _cfg_benefit_rate = null;

frappe.ui.form.on("Material Rate", {
	onload(frm) {
		frappe.db.get_doc("Costing Configuration", "Costing Configuration").then(cfg => {
			_cfg_financing_rate = cfg.supplier_financing_rate_pct;
			_cfg_benefit_rate = cfg.credit_benefit_rate_pct;
			_compute_60d_equivalent(frm);
		});
	},

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

	delivered_rate(frm) {
		_compute_60d_equivalent(frm);
	},

	credit_days(frm) {
		_compute_60d_equivalent(frm);
	},

	valid_from(frm) {
		if (!frm.doc.valid_from) return;
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

function _compute_60d_equivalent(frm) {
	if (_cfg_financing_rate === null) return;
	const rate = frm.doc.delivered_rate || 0;
	const credit = frm.doc.credit_days || 0;
	const gap = 60 - credit;
	const r = gap > 0 ? _cfg_financing_rate : _cfg_benefit_rate;
	const eq = rate + rate * (gap / 365) * (r / 100);
	frm.set_value("rate_60d_equivalent", Math.round(eq * 100) / 100);
}

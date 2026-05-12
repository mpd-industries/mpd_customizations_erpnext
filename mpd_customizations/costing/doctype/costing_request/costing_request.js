// Costing Request — form controller
// Zero business logic. Display and user interaction only.

const API = "mpd_customizations.costing.api.costing";

let _config_production_days = null;
let _config_financing_rate = null;
let _pending_fetch_result = null;

// ─── Initialisation ─────────────────────────────────────────────────────────

frappe.ui.form.on("Costing Request", {
	onload(frm) {
		frappe.db.get_doc("Costing Configuration", "Costing Configuration").then(cfg => {
			_config_production_days = cfg.production_days;
			_config_financing_rate = cfg.supplier_financing_rate_pct;

			if (frm.doc.__islocal) {
				if (!frm.doc.production_days) frm.set_value("production_days", cfg.production_days);
				if (!frm.doc.supplier_financing_rate_pct) frm.set_value("supplier_financing_rate_pct", cfg.supplier_financing_rate_pct);
			}
		});
	},

	refresh(frm) {
		const is_sales_view = _is_sales_view();

		if (is_sales_view) {
			_render_sales_view(frm);
			return;
		}

		_render_action_bar(frm);
		_apply_amber_indicators(frm);

		if (frm.doc.quantity_kg && frm.doc.confirmed_ex_factory_cost_per_kg) {
			const total = frm.doc.quantity_kg * frm.doc.confirmed_ex_factory_cost_per_kg;
			frm.dashboard.add_comment(
				`Total Ex-Factory (${frm.doc.quantity_kg} kg): ₹${total.toFixed(2)}`,
				"blue", true
			);
		}

		if (frm.doc.mode === "Pending Approval" && frappe.user.has_role("Costing Approver")) {
			_render_approval_banner(frm);
		}

		_load_and_render_combinations(frm);
		if (frm.doc.selected_combination) {
			_load_and_render_breakdown(frm);
		}

		if (_pending_fetch_result) {
			_show_rate_summary(frm, _pending_fetch_result);
			_pending_fetch_result = null;
		}
	},

	// ─── Item field ─────────────────────────────────────────────────────────

	item(frm) {
		if (!frm.doc.item) return;
		frappe.db.get_value("Item", frm.doc.item, "custom_solids_content_pct").then(r => {
			frm.set_value("solids_content_pct", r.message.custom_solids_content_pct || 0);
		});
		_load_previous_costing(frm);
	},

	// ─── Parameter fields ────────────────────────────────────────────────────

	production_days(frm) {
		_apply_amber_indicators(frm);
		_show_re_eval_banner(frm);
	},

	supplier_financing_rate_pct(frm) {
		_apply_amber_indicators(frm);
		_show_re_eval_banner(frm);
	},
});

// ─── Costing Rate Line child table ──────────────────────────────────────────

frappe.ui.form.on("Costing Rate Line", {
	working_rate(frm, cdt, cdn) {
		_on_rate_line_change(frm, cdt, cdn);
	},
	working_supplier_credit_days(frm, cdt, cdn) {
		_on_rate_line_change(frm, cdt, cdn);
	},
});

function _on_rate_line_change(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	const is_overridden =
		Math.round((row.working_rate || 0) * 100) / 100 !==
		Math.round((row.fetched_rate || 0) * 100) / 100 ||
		(row.working_supplier_credit_days || 0) !== (row.fetched_supplier_credit_days || 0);

	// Apply amber class
	const $row = $(frm.fields_dict.rate_lines.grid.get_row(cdn).$row);
	$row.toggleClass("bg-amber-50", is_overridden);

	if (!frm.doc.name || frm.doc.__islocal) return;

	frappe.call({
		method: `${API}.apply_rate_override`,
		args: {
			costing_request_name: frm.doc.name,
			item: row.item,
			working_rate: row.working_rate,
			working_supplier_credit_days: row.working_supplier_credit_days || 0,
			reason: row.override_reason || "",
		},
		callback(r) {
			if (r.message) _render_combinations(frm, r.message.combinations);
		},
	});
}

// ─── Action bar ─────────────────────────────────────────────────────────────

function _render_action_bar(frm) {
	frm.add_custom_button(__("Get Rates"), () => _on_get_rates(frm));

	if (frm.doc.selected_combination && frm.doc.mode === "Ready to Quote") {
		frm.add_custom_button(__("Submit for Approval"), () => frm.savesubmit(), __("Actions"));
	}

}

// ─── Sales View ──────────────────────────────────────────────────────────────

function _is_sales_view() {
	return !frappe.user.has_role("Costing Approver") &&
		!frappe.user.has_role("Costing User") &&
		!frappe.user.has_role("System Manager");
}

function _render_sales_view(frm) {
	// Hide technical fields from sales user
	["rate_lines", "scrap_lines", "processing_lines", "combinations_html", "cost_breakdown_html"].forEach(f => {
		try { frm.fields_dict[f].$wrapper.hide(); } catch (e) {}
	});

	const mode = frm.doc.mode || "Exploring";
	const stage1 = ["Exploring", "Awaiting Rates"].includes(mode);
	const stage2 = ["Partially Costed", "Ready to Quote"].includes(mode);
	const stage3 = ["Pending Approval", "Approved"].includes(mode);

	if (stage1) {
		frm.dashboard.add_comment(
			`⏳ Waiting for rates to be filled in. Click "Request Pending Rates" to notify the purchase team.`,
			"orange", true
		);
	} else if (stage2) {
		frm.add_custom_button(__("Submit for MD Approval"), () => frm.savesubmit());

		// Load combinations to show preferred + lowest
		frappe.call({
			method: `${API}.get_combinations`,
			args: { costing_request_name: frm.doc.name },
			callback(r) {
				if (!r.message) return;
				_render_sales_cost_summary(frm, r.message);
			},
		});
	} else if (stage3) {
		frm.dashboard.add_comment(
			mode === "Approved"
				? `✓ Approved. Confirmed rate: ₹${(frm.doc.confirmed_ex_factory_cost_per_kg || 0).toFixed(2)}/kg`
				: `⏳ Submitted for MD approval — awaiting review.`,
			mode === "Approved" ? "green" : "blue", true
		);
	}
}

function _render_sales_cost_summary(frm, combinations) {
	if (!combinations || !combinations.length) return;

	const preferred = combinations.find(c => c.is_preferred) || combinations.find(c => c.rank === 1);
	const lowest = combinations.find(c => c.rank === 1);
	const qty = frm.doc.quantity_kg || 0;

	function combo_html(combo, label) {
		if (!combo) return "";
		const total = combo.total_cost_per_kg || 0;
		const rm = combo.rm_cost_per_kg || 0;
		const proc = combo.processing_cost_per_kg || 0;
		const total_cost = qty ? `<br>Total (${qty} kg): <strong>₹${(total * qty).toFixed(2)}</strong>` : "";
		const status_color = combo.status === "Ready to Quote" ? "text-success" : "text-warning";

		return `
			<div class="mb-3 p-2 border rounded">
				<div class="font-weight-bold">${label}: ${frappe.utils.escape_html(combo.formulation_id || combo.bom)}</div>
				<div class="${status_color} small">${combo.status}</div>
				<table class="table table-sm mt-1 mb-0">
					<tr><td>RM Cost</td><td class="text-right">₹${rm.toFixed(2)}/kg</td></tr>
					<tr><td>Processing</td><td class="text-right">₹${proc.toFixed(2)}/kg</td></tr>
					<tr class="font-weight-bold"><td>Ex-Factory</td><td class="text-right">₹${total.toFixed(2)}/kg${total_cost}</td></tr>
				</table>
			</div>
		`;
	}

	const show_lowest = lowest && preferred && lowest.name !== preferred.name;
	const html = combo_html(preferred, "Preferred Formulation") +
		(show_lowest ? combo_html(lowest, "Lowest Cost Option") : "");

	frm.dashboard.add_comment(html, "blue", true);

	if (preferred && preferred.status !== "Ready to Quote") {
		frm.dashboard.add_comment(
			`⚠ Preferred formulation has missing/expired rates. You may request them or proceed with current values.`,
			"orange", true
		);
	}
}

// ─── Get Rates ───────────────────────────────────────────────────────────────

function _on_get_rates(frm) {
	const run = () => {
		const overridden_lines = (frm.doc.rate_lines || []).filter(rl =>
			Math.round((rl.working_rate || 0) * 100) / 100 !==
			Math.round((rl.fetched_rate || 0) * 100) / 100
		);
		if (overridden_lines.length > 0) {
			_show_override_dialog(frm, overridden_lines);
		} else {
			_do_evaluate(frm, true);
		}
	};

	if (frm.doc.__islocal || frm.is_dirty()) {
		frm.save().then(run);
	} else {
		run();
	}
}

function _show_override_dialog(frm, overridden_lines) {
	const table = overridden_lines.map(rl =>
		`<tr>
			<td>${rl.item_name || rl.item}</td>
			<td>₹${(rl.fetched_rate || 0).toFixed(2)}</td>
			<td>₹${(rl.working_rate || 0).toFixed(2)}</td>
		</tr>`
	).join("");

	const msg = `
		<p>${__("You have overridden the following rates:")}</p>
		<table class="table table-condensed">
			<thead><tr><th>${__("Item")}</th><th>${__("Official")}</th><th>${__("Your Value")}</th></tr></thead>
			<tbody>${table}</tbody>
		</table>
		<p>${__("What would you like to do?")}</p>
	`;

	const d = new frappe.ui.Dialog({
		title: __("Rate Overrides Exist"),
		fields: [{ fieldtype: "HTML", fieldname: "html", options: msg }],
		primary_action_label: __("Keep My Overrides"),
		primary_action() {
			d.hide();
			_do_evaluate(frm, true);
		},
		secondary_action_label: __("Reset to Official"),
		secondary_action() {
			d.hide();
			_do_evaluate(frm, false);
		},
	});
	d.show();
}

function _do_evaluate(frm, preserve_overrides) {
	frm.fields_dict.combinations_html.$wrapper.html(
		`<div class="text-muted p-4">${__("Evaluating formulations…")}</div>`
	);
	frm.disable_save();

	frappe.call({
		method: `${API}.evaluate`,
		args: { costing_request_name: frm.doc.name, trigger: preserve_overrides ? "preserve" : "reset" },
		callback(r) {
			frm.enable_save();
			if (r.message && r.message.fetch_result) {
				_pending_fetch_result = r.message.fetch_result;
			}
			frm.reload_doc();
		},
		error() { frm.enable_save(); },
	});
}

// ─── Combination cards ───────────────────────────────────────────────────────

function _load_and_render_combinations(frm) {
	frappe.call({
		method: `${API}.get_combinations`,
		args: { costing_request_name: frm.doc.name },
		callback(r) {
			if (r.message) _render_combinations(frm, r.message);
		},
	});
}

function _render_combinations(frm, combinations) {
	const $wrapper = frm.fields_dict.combinations_html.$wrapper;
	$wrapper.empty();

	if (!combinations || !combinations.length) {
		$wrapper.html(`<div class="text-muted p-4">${__("No combinations yet. Click Get Rates.")}</div>`);
		return;
	}

	// Switch alert
	const alert = frm.doc.formulation_switch_alert;
	if (alert) {
		const cheapest = combinations.find(c => c.rank === 1);
		const preferred = combinations.find(c => c.is_preferred);
		$wrapper.append(`
			<div class="alert alert-warning mb-4 p-3 border border-warning rounded">
				<strong>⚠ ${__("FORMULATION SWITCH RECOMMENDED")}</strong><br>
				${frappe.utils.escape_html(alert)}
				<div class="mt-2">
					${cheapest ? `<button class="btn btn-sm btn-primary mr-2" onclick="crSwitchFormulation('${frm.doc.name}', '${cheapest.name}', frm)">${__("Switch to")} ${cheapest.formulation_id || cheapest.bom}</button>` : ""}
					${preferred ? `<button class="btn btn-sm btn-secondary" onclick="crKeepFormulation()">${__("Keep")} ${preferred.formulation_id || preferred.bom}</button>` : ""}
				</div>
			</div>
		`);
	}

	const included = combinations.filter(c => c.status !== "Excluded — Too Expensive");
	const excluded = combinations.filter(c => c.status === "Excluded — Too Expensive");

	[...included, ...excluded].forEach(combo => {
		$wrapper.append(_render_combination_card(frm, combo));
	});
}

function _render_combination_card(frm, combo) {
	const is_excluded = combo.status === "Excluded — Too Expensive";
	const selected_class = combo.is_selected ? "border-primary shadow" : "";
	const preferred_badge = combo.is_preferred ? `<span class="badge badge-info ml-2">★ ${__("Preferred")}</span>` : "";
	const rank_badge = combo.rank ? `<span class="badge badge-secondary ml-2">${__("Rank")} ${combo.rank}</span>` : "";

	const status_color = {
		"Ready to Quote": "text-success",
		"Indicative — Rates Expired": "text-warning",
		"Indicative — Rates Missing": "text-danger",
		"Excluded — Too Expensive": "text-muted",
	}[combo.status] || "";

	if (is_excluded) {
		return `
			<div class="card mb-3 ${selected_class}" style="opacity:0.7">
				<div class="card-body d-flex justify-content-between align-items-center">
					<div>
						<strong>${combo.formulation_id || combo.bom}</strong>
						<span class="text-muted ml-2">EXCLUDED +${(combo.delta_pct || 0).toFixed(1)}% vs cheapest</span>
					</div>
					<button class="btn btn-sm btn-outline-secondary"
						onclick="crIncludeCombination('${frm.doc.name}', '${combo.name}', '${frm.doc.name}')">
						${__("Include Anyway")}
					</button>
				</div>
			</div>
		`;
	}

	const details_id = `combo-detail-${combo.name.replace(/[^a-z0-9]/gi, "")}`;
	const ml_rows = (combo.material_lines || []).map(ml => {
		const is_scrap = ml.is_scrap;
		const scrap_label = is_scrap ? ' <span class="text-success">(Scrap / Byproduct)</span>' : "";
		const amount_display = is_scrap
			? `<span class="text-success">−₹${Math.abs(ml.amount_per_kg || 0).toFixed(2)}/kg</span>`
			: `₹${(ml.amount_per_kg || 0).toFixed(2)}/kg`;
		const rate_label = is_scrap
			? `₹${(ml.working_rate || 0).toFixed(2)} <span class="text-muted small">(byproduct rate)</span>`
			: `₹${(ml.working_rate || 0).toFixed(2)} <span class="text-muted small">(60d eq.)</span>`;
		const sub_row = is_scrap
			? `<em>byproduct — no supplier</em>`
			: `${ml.supplier || "—"} | actual ${ml.working_supplier_credit_days || 0}d credit | ${ml.net_financed_days || 0}d financed beyond 60d`;
		return `<tr class="${is_scrap ? "table-success" : ""}">
			<td>${ml.item_name || ml.item}${scrap_label}</td>
			<td>${(ml.qty_per_kg_output || 0).toFixed(4)} × ${rate_label}</td>
			<td class="text-right">${amount_display}</td>
		</tr>
		<tr class="text-muted small"><td colspan="3">&nbsp;&nbsp;${sub_row}</td></tr>`;
	}).join("");

	return `
		<div class="card mb-3 ${selected_class}">
			<div class="card-header d-flex justify-content-between align-items-center">
				<div>
					<strong>${combo.formulation_id || combo.bom}</strong>
					${rank_badge}${preferred_badge}
				</div>
				<span class="${status_color}">${combo.status}</span>
			</div>
			<div class="card-body">
				<div class="row">
					<div class="col-md-8">
						<table class="table table-sm mb-0">
							<tr><td>${__("Raw Material Cost")}</td><td class="text-right">₹${(combo.rm_cost_per_kg || 0).toFixed(2)}/kg</td></tr>
							<tr><td>${__("Financing Cost")}</td><td class="text-right">₹${(combo.financing_cost_per_kg || 0).toFixed(2)}/kg</td></tr>
							<tr><td>${__("Processing Cost")}</td><td class="text-right">₹${(combo.processing_cost_per_kg || 0).toFixed(2)}/kg</td></tr>
							<tr><td>${__("Additional Charges")}</td><td class="text-right">₹${(combo.additional_charges_per_kg || 0).toFixed(2)}/kg</td></tr>
							<tr><td>${__("Outward Freight")}</td><td class="text-right">₹${(combo.outward_freight_per_kg || 0).toFixed(2)}/kg</td></tr>
							<tr class="font-weight-bold border-top"><td>${__("TOTAL EX-FACTORY")}</td><td class="text-right">₹${(combo.total_cost_per_kg || 0).toFixed(2)}/kg</td></tr>
						</table>
						<button class="btn btn-link btn-sm p-0 small text-muted"
							data-toggle="collapse" data-target="#${details_id}">
							${__("Show ingredient detail")} ▼
						</button>
						<div class="collapse" id="${details_id}">
							<table class="table table-sm mt-2">${ml_rows}</table>
						</div>
					</div>
					<div class="col-md-4 d-flex align-items-end justify-content-end">
						<button class="btn btn-primary btn-sm"
							onclick="crSelectCombination('${frm.doc.name}', '${combo.name}')">
							${__("Select This Formulation")}
						</button>
					</div>
				</div>
			</div>
		</div>
	`;
}

// Global helpers called from inline onclick (Frappe HTML fields require global scope)
window.crSelectCombination = function(cr_name, combo_name) {
	frappe.call({
		method: `${API}.select_combination`,
		args: { costing_request_name: cr_name, combination_name: combo_name },
		callback(r) {
			if (r.message) {
				frappe.show_alert({ message: __("Formulation selected"), indicator: "green" });
				cur_frm.reload_doc();
			}
		},
	});
};

window.crSwitchFormulation = function(cr_name, combo_name) {
	crSelectCombination(cr_name, combo_name);
};

window.crKeepFormulation = function() {
	frappe.show_alert({ message: __("Keeping current formulation"), indicator: "blue" });
};

window.crIncludeCombination = function(_cr_name, combo_name) {
	frappe.db.set_value("Costing Combination", combo_name, "status", "Ready to Quote").then(() => {
		cur_frm.reload_doc();
	});
};

// ─── Cost Breakdown ──────────────────────────────────────────────────────────

function _load_and_render_breakdown(frm) {
	frappe.call({
		method: `${API}.get_cost_breakdown`,
		args: { costing_request_name: frm.doc.name },
		callback(r) {
			if (r.message) _render_cost_breakdown(frm, r.message);
		},
	});
}

function _render_cost_breakdown(frm, data) {
	const $wrapper = frm.fields_dict.cost_breakdown_html.$wrapper;
	$wrapper.empty();

	if (!data || !data.layer1) return;

	const l = data.layer1;

	// Sort by absolute amount descending (highest cost drivers first)
	const sorted_lines = [...(l.material_lines || [])].sort(
		(a, b) => Math.abs(b.amount_per_kg || 0) - Math.abs(a.amount_per_kg || 0)
	);
	const rm_rows = sorted_lines.map(ml => {
		const is_scrap = ml.is_scrap;
		// Only flag override when fetched_rate is actually set and genuinely differs
		const overridden = !is_scrap && ml.fetched_rate && ml.is_overridden;
		const override_note = overridden ? ` ⚠ <em>(official ₹${ml.fetched_rate.toFixed(2)})</em>` : "";
		const scrap_note = is_scrap ? ' <span class="text-success">(Scrap Credit)</span>' : "";
		const amount_fmt = is_scrap
			? `<strong class="text-success">−₹${Math.abs(ml.amount_per_kg || 0).toFixed(2)}/kg</strong>`
			: `<strong>₹${(ml.amount_per_kg || 0).toFixed(2)}/kg</strong>`;
		const rate_history_url = `/app/material-rate?item=${encodeURIComponent(ml.item)}${ml.city ? "&city=" + encodeURIComponent(ml.city) : ""}`;
		const source_link = ml.rate_source_ref
			? `<a href="/app/material-rate/${encodeURIComponent(ml.rate_source_ref)}" target="_blank">${ml.rate_source_ref}</a>`
			: "—";
		const detail_line = is_scrap
			? `${(ml.qty_per_kg_output || 0).toFixed(4)} kg × ₹${(ml.working_rate || 0).toFixed(2)}/kg = ${amount_fmt} <em class="small">(byproduct — no supplier)</em>`
			: `${(ml.qty_per_kg_output || 0).toFixed(4)} kg × ₹${(ml.working_rate || 0).toFixed(2)}/kg (60d eq.) = ${amount_fmt}<br>
				${ml.supplier || "—"} | actual ${ml.working_supplier_credit_days || 0}d credit | ${ml.net_financed_days || 0}d financed beyond 60d
				| Financing: ₹${(ml.financing_cost_per_kg || 0).toFixed(2)}/kg | Source: ${source_link}`;
		return `<div class="ml-3 mb-2 ${is_scrap ? "text-success" : ""}">
			<strong>${ml.item_name || ml.item}</strong>${scrap_note}${override_note}
			${!is_scrap ? `<a href="${rate_history_url}" target="_blank" class="small ml-2 text-muted">Rate History ↗</a>` : ""}
			<br><span class="text-muted">${detail_line}</span>
		</div>`;
	}).join("");

	const add_rows = (l.additional_charges || []).map(c =>
		`<div class="ml-3">${c.description} (${c.basis}) — ₹${(c.amount_per_kg || 0).toFixed(2)}/kg</div>`
	).join("");

	let layer3_html = "";
	if (data.layer3) {
		const l3 = data.layer3;
		const spread_rows = (l3.rm_spread_breakdown || []).map(s =>
			`<div class="ml-3 text-muted">
				${s.item_name || s.item}: ₹${(s.amount_per_kg || 0).toFixed(2)} × (${s.net_financed_days}d/365) × ${l3.spread_pct}%
				= ₹${(s.spread_per_kg || 0).toFixed(4)}/kg
			</div>`
		).join("");

		layer3_html = `
			<hr>
			<div class="text-center font-weight-bold text-danger mb-2">══ INTERNAL EARNINGS ANALYSIS — CONFIDENTIAL ══</div>
			<div>RM Financing Spread: charged at ${l3.supplier_financing_rate_pct}% pa, actual cost ${l3.actual_cost_of_capital_pct}% pa, spread = ${l3.spread_pct}% pa</div>
			${spread_rows}
			<div class="font-weight-bold mt-1">RM Spread per kg: ₹${(l3.rm_spread_per_kg || 0).toFixed(4)}/kg</div>
		`;
	}

	$wrapper.html(`
		<div class="p-3 border rounded">
			<div class="text-center font-weight-bold mb-3">
				━━ COST BREAKDOWN — ${frappe.utils.escape_html(l.formulation_id || l.bom)} ━━
			</div>
			<div class="font-weight-bold">RAW MATERIAL COST</div>
			${rm_rows}
			<div class="font-weight-bold mt-2">FINANCING COST (${l.supplier_financing_rate_pct}% pa, ${Math.max(0, l.production_days - 60)} days beyond 60d baseline)</div>
			<div class="ml-3 text-muted">See per-ingredient detail above</div>
			<div class="font-weight-bold mt-2">PROCESSING COST</div>
			<div class="ml-3">${l.solids_content_pct}% solids × ₹${(l.processing_cost_per_kg / (l.solids_content_pct / 100) || 0).toFixed(2)}/kg = ₹${(l.processing_cost_per_kg || 0).toFixed(2)}/kg</div>
			<div class="font-weight-bold mt-2">ADDITIONAL CHARGES</div>
			${add_rows || '<div class="ml-3 text-muted">None</div>'}
			<div class="font-weight-bold mt-2">OUTWARD FREIGHT: ₹${(l.outward_freight_per_kg || 0).toFixed(2)}/kg</div>
			<hr>
			<div class="font-weight-bold text-primary">CONFIRMED EX-FACTORY COST: ₹${(l.total_cost_per_kg || 0).toFixed(2)}/kg</div>
			${layer3_html}
		</div>
	`);
}

// ─── Previous costing prefill ────────────────────────────────────────────────

function _load_previous_costing(frm) {
	if (!frm.doc.item) return;
	frappe.call({
		method: `${API}.get_previous_costing`,
		args: { item: frm.doc.item },
		callback(r) {
			if (!r.message) return;
			const prev = r.message;
			frm.set_value("preferred_bom", prev.preferred_bom || "");
			frm.set_value("previous_costing_ref", prev.name);
			frm.set_value("production_days", prev.production_days);
			frm.set_value("supplier_financing_rate_pct", prev.supplier_financing_rate_pct);

			if (prev.additional_charges && prev.additional_charges.length) {
				frm.clear_table("additional_charges");
				prev.additional_charges.forEach(c => {
					const row = frm.add_child("additional_charges");
					row.description = c.description;
					row.basis = c.basis;
					row.rate = c.rate;
				});
				frm.refresh_field("additional_charges");
			}

			frm.dashboard.add_comment(
				__(`Pre-filled from last approved costing <a href="/app/costing-request/${prev.name}">${prev.name}</a>.`),
				"blue",
				true
			);
		},
	});
}

// ─── MD approval banner ──────────────────────────────────────────────────────

function _render_approval_banner(frm) {
	const overrides = (frm.doc.rate_lines || []).filter(rl =>
		Math.round((rl.working_rate || 0) * 100) / 100 !==
		Math.round((rl.fetched_rate || 0) * 100) / 100
	);

	const override_lines = overrides.map(rl => {
		const diff_pct = rl.fetched_rate
			? (((rl.working_rate - rl.fetched_rate) / rl.fetched_rate) * 100).toFixed(1)
			: "—";
		return `· ${rl.item_name || rl.item}: ₹${(rl.fetched_rate || 0).toFixed(2)} → ₹${(rl.working_rate || 0).toFixed(2)} (${diff_pct}%)`;
	}).join("<br>");

	frm.dashboard.add_comment(`
		<strong>PENDING YOUR APPROVAL</strong><br>
		Selected: ${frm.doc.selected_combination || "—"}<br>
		Confirmed Ex-Factory Cost: ₹${(frm.doc.confirmed_ex_factory_cost_per_kg || 0).toFixed(2)}/kg<br>
		Rate Overrides: ${overrides.length}<br>
		${override_lines}
	`, overrides.length > 0 ? "orange" : "blue", true);

	if (!frm.doc.docstatus || frm.doc.docstatus < 1) return;

	frm.add_custom_button(__("Approve"), () => {
		frappe.db.set_value("Costing Request", frm.doc.name, "mode", "Approved").then(() => {
			frappe.show_alert({ message: __("Costing approved"), indicator: "green" });
			frm.reload_doc();
		});
	}, __("Approval"));

	frm.add_custom_button(__("Reject"), () => {
		frappe.prompt(
			{ fieldname: "reason", label: __("Rejection Reason"), fieldtype: "Small Text", reqd: 1 },
			values => {
				frappe.db.set_value("Costing Request", frm.doc.name, {
					mode: "Rejected",
					formulation_switch_alert: `Rejected: ${values.reason}`,
				}).then(() => {
					frappe.show_alert({ message: __("Costing rejected"), indicator: "red" });
					frm.reload_doc();
				});
			},
			__("Reject Costing"),
			__("Reject")
		);
	}, __("Approval"));
}

// ─── Rate summary line ───────────────────────────────────────────────────────

function _show_rate_summary(frm, fetch_result) {
	if (!fetch_result) return;
	const parts = [];
	if (fetch_result.has_expired_rates) parts.push(`⚠ ${fetch_result.expired_items.length} rate(s) expired`);
	if (fetch_result.has_missing_rates) parts.push(`✗ ${fetch_result.missing_items.length} rate(s) missing`);
	if (parts.length) {
		frm.dashboard.add_comment(parts.join("  ·  "), fetch_result.has_missing_rates ? "red" : "orange", true);
	}

	// Supplier count from rate_lines
	const suppliers = [...new Set(
		(frm.doc.rate_lines || [])
			.map(rl => rl.supplier)
			.filter(Boolean)
	)];
	if (suppliers.length) {
		frm.dashboard.add_comment(
			`Rates from ${suppliers.length} supplier(s): ${suppliers.join(", ")}`,
			"blue",
			true
		);
	}
}

// ─── Amber indicators ────────────────────────────────────────────────────────

function _apply_amber_indicators(frm) {
	if (_config_production_days !== null) {
		const changed = (frm.doc.production_days || 0) !== _config_production_days;
		frm.get_field("production_days").$wrapper.toggleClass("has-warning", changed);
	}
	if (_config_financing_rate !== null) {
		const changed = (frm.doc.supplier_financing_rate_pct || 0) !== _config_financing_rate;
		frm.get_field("supplier_financing_rate_pct").$wrapper.toggleClass("has-warning", changed);
	}
}

function _show_re_eval_banner(frm) {
	if (frm.doc.last_evaluated_on) {
		frm.dashboard.add_comment(
			__("Parameters changed since last evaluation. Click Get Rates to re-evaluate."),
			"orange",
			true
		);
	}
}

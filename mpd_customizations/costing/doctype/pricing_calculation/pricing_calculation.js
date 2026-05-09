// Pricing Calculation — costing team form
// Internal use only. No sales-facing logic here.

const API = "mpd_customizations.costing.api.costing";

let _config_production_days = null;
let _config_financing_rate = null;
let _pending_fetch_result = null;

// ─── Initialisation ─────────────────────────────────────────────────────────

frappe.ui.form.on("Pricing Calculation", {
	onload(frm) {
		frappe.db.get_doc("Costing Configuration", "Costing Configuration").then(cfg => {
			_config_production_days = cfg.production_days;
			_config_financing_rate = cfg.supplier_financing_rate_pct;
		});
	},

	refresh(frm) {
		_render_request_breadcrumb(frm);
		_render_action_bar(frm);
		_apply_amber_indicators(frm);

		if (frm.doc.confirmed_ex_factory_cost_per_kg) {
			frm.dashboard.add_comment(
				`Ex-Factory: ₹${frm.doc.confirmed_ex_factory_cost_per_kg.toFixed(2)}/kg`,
				"blue", true
			);
		}

		if (frm.doc.mode === "Ready to Quote" && frappe.user.has_role("Costing Approver")) {
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

	// ─── Parameter fields ────────────────────────────────────────────────────────

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

	const $row = $(frm.fields_dict.rate_lines.grid.get_row(cdn).$row);
	$row.toggleClass("bg-amber-50", is_overridden);

	if (!frm.doc.name || frm.doc.__islocal) return;

	frappe.call({
		method: `${API}.apply_rate_override`,
		args: {
			pricing_calculation_name: frm.doc.name,
			item: row.item,
			working_rate: row.working_rate,
			working_supplier_credit_days: row.working_supplier_credit_days || 0,
			reason: row.override_reason || "",
		},
		callback(r) {
			if (r.message) {
				if (r.message.modified) frm.doc.modified = r.message.modified;
				_render_combinations(frm, r.message.combinations);
			}
		},
	});
}

// ─── Request breadcrumb ──────────────────────────────────────────────────────

function _render_request_breadcrumb(frm) {
	if (!frm.doc.pricing_request) return;

	// Fetch priority from linked PR to show at top
	frappe.db.get_value("Pricing Request", frm.doc.pricing_request, ["priority", "status", "quantity_kg", "product_name"]).then(r => {
		if (!r.message) return;
		const pr = r.message;
		const priority_color = { "Urgent": "red", "High": "orange", "Normal": "blue", "Low": "gray" }[pr.priority] || "blue";
		frm.dashboard.add_comment(
			`Pricing Request: <a href="/app/pricing-request/${frm.doc.pricing_request}">${frm.doc.pricing_request}</a>
			· <strong style="color:${priority_color}">Priority: ${pr.priority}</strong>
			· Status: ${pr.status}${pr.quantity_kg ? ` · Qty: ${pr.quantity_kg} kg` : ""}`,
			priority_color === "red" ? "red" : "blue",
			true
		);
	});
}

// ─── Action bar ─────────────────────────────────────────────────────────────

function _render_action_bar(frm) {
	frm.add_custom_button(__("Get Rates"), () => _on_get_rates(frm));

	if (frm.doc.last_evaluated_on &&
		(frm.doc.mode === "Awaiting Rates" || frm.doc.mode === "Ready for Working")) {
		frm.add_custom_button(__("Create Pending Rates"), () => _on_create_pending_rates(frm));
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
		args: { pricing_calculation_name: frm.doc.name, trigger: preserve_overrides ? "preserve" : "reset" },
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
		args: { pricing_calculation_name: frm.doc.name },
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

	const alert = frm.doc.formulation_switch_alert;
	if (alert) {
		const cheapest = combinations.find(c => c.rank === 1);
		const preferred = combinations.find(c => c.is_preferred);
		$wrapper.append(`
			<div class="alert alert-warning mb-3 p-3 border border-warning rounded">
				<strong>⚠ ${__("FORMULATION SWITCH RECOMMENDED")}</strong><br>
				${frappe.utils.escape_html(alert)}
				<div class="mt-2">
					${cheapest ? `<button class="btn btn-sm btn-primary mr-2" onclick="pcSwitchFormulation('${frm.doc.name}', '${cheapest.name}')">${__("Switch to")} ${cheapest.formulation_id || cheapest.bom}</button>` : ""}
					${preferred ? `<button class="btn btn-sm btn-secondary" onclick="pcKeepFormulation()">${__("Keep")} ${preferred.formulation_id || preferred.bom}</button>` : ""}
				</div>
			</div>
		`);
	}

	const included = combinations.filter(c => c.status !== "Excluded — Too Expensive");
	const excluded = combinations.filter(c => c.status === "Excluded — Too Expensive");
	const rows = [...included, ...excluded].map(combo => _render_combination_row(frm, combo)).join("");

	$wrapper.append(`
		<table class="table table-sm table-bordered mb-0" style="table-layout:fixed">
			<thead class="thead-light">
				<tr>
					<th style="width:36px"></th>
					<th>${__("Formulation")}</th>
					<th style="width:180px">${__("Status")}</th>
					<th class="text-right" style="width:90px">${__("RM")}</th>
					<th class="text-right" style="width:90px">${__("Fin.")}</th>
					<th class="text-right" style="width:90px">${__("Proc.")}</th>
					<th class="text-right" style="width:90px">${__("Other")}</th>
					<th class="text-right" style="width:100px"><strong>${__("Total/kg")}</strong></th>
					<th style="width:110px"></th>
				</tr>
			</thead>
			<tbody>${rows}</tbody>
		</table>
	`);
}

function _render_combination_row(frm, combo) {
	const is_excluded = combo.status === "Excluded — Too Expensive";
	const is_selected = combo.is_selected;
	const detail_id = `combo-detail-${combo.name.replace(/[^a-z0-9]/gi, "")}`;
	const other = (combo.additional_charges_per_kg || 0) + (combo.outward_freight_per_kg || 0);

	const status_color = {
		"Ready to Quote": "success",
		"Indicative — Rates Expired": "warning",
		"Indicative — Rates Missing": "danger",
		"Excluded — Too Expensive": "secondary",
	}[combo.status] || "secondary";

	const badges = [
		combo.is_preferred ? `<span class="badge badge-info">★</span>` : "",
		combo.rank && !is_excluded ? `<span class="badge badge-light border">#${combo.rank}</span>` : "",
		is_excluded ? `<span class="badge badge-secondary">+${(combo.delta_pct || 0).toFixed(1)}%</span>` : "",
	].filter(Boolean).join(" ");

	const row_class = is_selected
		? "table-primary"
		: is_excluded ? "text-muted" : "";

	const action_btn = is_excluded
		? `<button class="btn btn-sm btn-outline-secondary btn-block" onclick="pcIncludeCombination('${combo.name}')">${__("Include")}</button>`
		: is_selected
			? `<button class="btn btn-sm btn-success btn-block" disabled>✓ ${__("Selected")}</button>`
			: `<button class="btn btn-sm btn-outline-primary btn-block" onclick="pcSelectCombination('${frm.doc.name}', '${combo.name}')">${__("Select")}</button>`;

	// Expanded ingredient detail rows
	const ml_rows = (combo.material_lines || []).map(ml => {
		const is_scrap = ml.is_scrap;
		const amount = is_scrap
			? `<span class="text-success">−₹${Math.abs(ml.amount_per_kg || 0).toFixed(2)}</span>`
			: `₹${(ml.amount_per_kg || 0).toFixed(2)}`;
		return `
			<tr class="${is_scrap ? "table-success" : ""}">
				<td colspan="2">${ml.item_name || ml.item}${is_scrap ? ' <em class="text-muted small">(byproduct)</em>' : ""}</td>
				<td class="text-right text-muted small">${(ml.qty_per_kg_output || 0).toFixed(4)} × ₹${(ml.working_rate || 0).toFixed(2)}</td>
				<td class="text-right" colspan="2">${is_scrap ? "" : (ml.supplier || "—") + " " + (ml.working_supplier_credit_days || 0) + "d"}</td>
				<td class="text-right">${amount}/kg</td>
				<td class="text-right text-muted small">+₹${(ml.financing_cost_per_kg || 0).toFixed(3)} fin.</td>
				<td colspan="2"></td>
			</tr>`;
	}).join("");

	const breakdown_row = `
		<tr class="table-light small">
			<td></td>
			<td colspan="2" class="text-muted pl-3">
				<em>${__("RM")} ₹${(combo.rm_cost_per_kg || 0).toFixed(2)}
				+ ${__("Fin.")} ₹${(combo.financing_cost_per_kg || 0).toFixed(2)}
				+ ${__("Proc.")} ₹${(combo.processing_cost_per_kg || 0).toFixed(2)}
				+ ${__("Other")} ₹${other.toFixed(2)}
				= <strong>₹${(combo.total_cost_per_kg || 0).toFixed(2)}/kg</strong></em>
			</td>
			<td colspan="6"></td>
		</tr>
		${ml_rows}`;

	return `
		<tr class="${row_class}" style="${is_excluded ? "opacity:0.65" : ""}">
			<td class="text-center">
				<button class="btn btn-link btn-sm p-0 combo-expand-btn" style="font-size:11px;line-height:1"
					data-detail="${detail_id}" onclick="pcToggleDetail(this)">▶</button>
			</td>
			<td><strong>${combo.formulation_id || combo.bom}</strong> ${badges}</td>
			<td><span class="text-${status_color} small">${combo.status}</span></td>
			<td class="text-right">₹${(combo.rm_cost_per_kg || 0).toFixed(2)}</td>
			<td class="text-right text-muted">₹${(combo.financing_cost_per_kg || 0).toFixed(2)}</td>
			<td class="text-right text-muted">₹${(combo.processing_cost_per_kg || 0).toFixed(2)}</td>
			<td class="text-right text-muted">₹${other.toFixed(2)}</td>
			<td class="text-right"><strong>₹${(combo.total_cost_per_kg || 0).toFixed(2)}</strong></td>
			<td>${action_btn}</td>
		</tr>
		<tr id="${detail_id}" style="display:none" class="bg-light">
			${breakdown_row}
		</tr>`;
}

window.pcToggleDetail = function(btn) {
	const id = btn.getAttribute("data-detail");
	const row = document.getElementById(id);
	const hidden = row.style.display === "none";
	row.style.display = hidden ? "table-row" : "none";
	btn.textContent = hidden ? "▼" : "▶";
};

window.pcSelectCombination = function(pc_name, combo_name) {
	frappe.call({
		method: `${API}.select_combination`,
		args: { pricing_calculation_name: pc_name, combination_name: combo_name },
		callback(r) {
			if (r.message) {
				frappe.show_alert({ message: __("Formulation selected"), indicator: "green" });
				cur_frm.reload_doc();
			}
		},
	});
};

window.pcSwitchFormulation = function(pc_name, combo_name) {
	pcSelectCombination(pc_name, combo_name);
};

window.pcKeepFormulation = function() {
	frappe.show_alert({ message: __("Keeping current formulation"), indicator: "blue" });
};

window.pcIncludeCombination = function(combo_name) {
	frappe.db.set_value("Costing Combination", combo_name, "status", "Ready to Quote").then(() => {
		cur_frm.reload_doc();
	});
};

// ─── Cost Breakdown ──────────────────────────────────────────────────────────

function _load_and_render_breakdown(frm) {
	frappe.call({
		method: `${API}.get_cost_breakdown`,
		args: { pricing_calculation_name: frm.doc.name },
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

	const sorted_lines = [...(l.material_lines || [])].sort(
		(a, b) => Math.abs(b.amount_per_kg || 0) - Math.abs(a.amount_per_kg || 0)
	);
	const rm_rows = sorted_lines.map(ml => {
		const is_scrap = ml.is_scrap;
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

// ─── Create Pending Rates ────────────────────────────────────────────────────

function _on_create_pending_rates(frm) {
	frappe.call({
		method: `${API}.create_pending_rates`,
		args: { pricing_calculation_name: frm.doc.name },
		callback(r) {
			if (r.message) {
				const count = r.message.created_count;
				frappe.show_alert({
					message: __("{0} pending rate request(s) created", [count]),
					indicator: count > 0 ? "green" : "blue",
				});
				if (count > 0) {
					frm.dashboard.add_comment(
						__(`${count} pending rate(s) created for purchase team. <a href="/app/material-rate?docstatus=0">View them</a>.`),
						"blue",
						true
					);
				}
			}
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
		<strong>READY TO QUOTE</strong><br>
		Selected: ${frm.doc.selected_combination || "—"}<br>
		Confirmed Ex-Factory Cost: ₹${(frm.doc.confirmed_ex_factory_cost_per_kg || 0).toFixed(2)}/kg<br>
		Rate Overrides: ${overrides.length}<br>
		${override_lines}
	`, overrides.length > 0 ? "orange" : "green", true);
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

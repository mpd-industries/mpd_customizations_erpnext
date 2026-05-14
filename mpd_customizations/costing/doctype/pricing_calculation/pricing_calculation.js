// Pricing Calculation — costing team form
// Internal use only. No sales-facing logic here.

const API = "mpd_customizations.costing.api.costing";

let _config_production_days = null;
let _pending_fetch_result = null;
const _auto_evaluated = new Set();  // tracks which PC names have been synced this session

function _parse_raw(str) {
	if (!str) return {};
	try { return JSON.parse(str); } catch(e) { return {}; }
}

// ─── Initialisation ─────────────────────────────────────────────────────────

frappe.ui.form.on("Pricing Calculation", {
	onload(_frm) {
		frappe.db.get_doc("Costing Configuration", "Costing Configuration").then(cfg => {
			_config_production_days = cfg.production_days;
		});
	},

	refresh(frm) {
		_render_request_breadcrumb(frm);
		_render_action_bar(frm);
		_apply_amber_indicators(frm);

		if (frm.doc.confirmed_selling_price_per_kg) {
			frm.dashboard.add_comment(
				`<strong>Selling: ₹${frm.doc.confirmed_selling_price_per_kg.toFixed(2)}/kg</strong>`,
				"blue",
				true
			);
		}

		if ((frm.doc.mode === "Ready to Quote" || frm.doc.mode === "Approved") && frappe.user.has_role("Costing Approver")) {
			_render_approval_banner(frm);
		}

		_load_and_render_combinations(frm);

		if (_pending_fetch_result) {
			_show_rate_summary(frm, _pending_fetch_result);
			_pending_fetch_result = null;
		}

		// Auto-fetch fresh rates once per session when the form first opens (draft only)
		if (!frm.doc.__islocal && frm.doc.docstatus === 0 && !_auto_evaluated.has(frm.doc.name)) {
			_auto_evaluated.add(frm.doc.name);
			_do_evaluate(frm);
		}
	},

	// ─── Parameter fields ────────────────────────────────────────────────────────

	customer_product_ref(frm) {
		if (!frm.doc.customer_product_ref) return;
		frappe.db.get_list("Customer Product Formulation", {
			filters: { parent: frm.doc.customer_product_ref },
			fields: ["bom"],
			limit: 1,
		}).then(rows => {
			if (!rows || !rows.length || !rows[0].bom) return Promise.resolve(null);
			return frappe.db.get_value("BOM", rows[0].bom, "item");
		}).then(r => {
			if (!r || !r.message) return Promise.resolve(null);
			return frappe.db.get_value("Item", r.message.item, "custom_solids_content_pct");
		}).then(r => {
			if (r && r.message && r.message.custom_solids_content_pct) {
				frm.set_value("solids_content_pct", r.message.custom_solids_content_pct);
			}
		});
	},

	processor(frm) {
		if (!frm.doc.processor || !frm.doc.item || frm.doc.__islocal) return;
		const do_fetch = () => frappe.call({
			method: `${API}.fetch_processing_charge`,
			args: { pricing_calculation_name: frm.doc.name },
			callback(r) {
				if (r.message) {
					frappe.show_alert({ message: __("Processing charge loaded"), indicator: "green" });
					frm.reload_doc();
				} else {
					frappe.show_alert({ message: __("No processing charge found for this processor"), indicator: "orange" });
				}
			},
		});
		if (frm.is_dirty()) {
			frm.save().then(do_fetch);
		} else {
			do_fetch();
		}
	},

	production_days(frm) {
		_apply_amber_indicators(frm);
	},

});

// ─── Costing Rate Line child table ──────────────────────────────────────────

frappe.ui.form.on("Costing Rate Line", {
	form_render(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.rate_valid_to) return;
		const days_left = frappe.datetime.get_diff(row.rate_valid_to, frappe.datetime.get_today());
		const $row = frm.fields_dict.rate_lines.grid.get_row(cdn).$row;
		$row.toggleClass("bg-amber-50", days_left >= 0 && days_left <= 30);
	},
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
		callback() { frm.reload_doc(); },
	});
}

// ─── Auto-evaluation ─────────────────────────────────────────────────────────

function _do_evaluate(frm) {
	// Silent full rate-fetch — called once per session on form open
	frappe.call({
		method: `${API}.evaluate`,
		args: { pricing_calculation_name: frm.doc.name, trigger: "preserve" },
		callback(r) {
			if (r.message && r.message.fetch_result) {
				_pending_fetch_result = r.message.fetch_result;
			}
			// reload_doc is safe here — _auto_evaluated already has this name,
			// so the next refresh will not trigger another evaluate
			frm.reload_doc();
		},
	});
}

// ─── Request breadcrumb ──────────────────────────────────────────────────────

function _render_request_breadcrumb(frm) {
	if (!frm.doc.pricing_request) return;

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
	if (frm.doc.mode === "Ready to Quote" && frappe.user.has_role("Costing Approver")) {
		frm.add_custom_button(__("Approve"), () => {
			frappe.call({
				method: `${API}.approve_pricing_calculation`,
				args: { pricing_calculation_name: frm.doc.name },
				callback(r) {
					if (r.message) {
						frappe.show_alert({ message: __("Approved — pricing request fulfilled"), indicator: "green" });
						frm.reload_doc();
					}
				},
			});
		}, __("Decision"));

		frm.add_custom_button(__("Reject"), () => {
			frappe.call({
				method: `${API}.reject_pricing_calculation`,
				args: { pricing_calculation_name: frm.doc.name },
				callback(r) {
					if (r.message) {
						frappe.show_alert({ message: __("Rejected"), indicator: "red" });
						frm.reload_doc();
					}
				},
			});
		}, __("Decision"));
	}


	if (frm.doc.docstatus === 0) {
		const _rate_ov = (frm.doc.rate_lines || []).filter(rl =>
			Math.round((rl.working_rate || 0) * 100) / 100 !==
			Math.round((rl.fetched_rate || 0) * 100) / 100
		);
		const _proc_ov = (frm.doc.processing_lines || []).filter(pl =>
			pl.fetched_charge_per_kg &&
			Math.round((pl.working_charge_per_kg || 0) * 100) / 100 !==
			Math.round((pl.fetched_charge_per_kg || 0) * 100) / 100
		);
		if (_rate_ov.length + _proc_ov.length > 0) {
			frm.add_custom_button(
				`⚠ Overrides (${_rate_ov.length + _proc_ov.length})`,
				() => _show_overrides_dialog(frm)
			);
		}

		const _freight_ov = (frm.doc.delivery_lines || []).filter(dl =>
			(dl.rate_freshness === "Missing" && (dl.working_freight_per_kg || 0) > 0) ||
			Math.round((dl.working_freight_per_kg || 0) * 10000) / 10000 !==
			Math.round((dl.fetched_freight_per_kg || 0) * 10000) / 10000
		);
		if (_freight_ov.length > 0) {
			frm.add_custom_button(
				`🚚 Save Freight to Master (${_freight_ov.length})`,
				() => _show_freight_promote_dialog(frm, _freight_ov)
			);
		}
	}
}

// ─── Overrides dialog ────────────────────────────────────────────────────────

function _show_overrides_dialog(frm) {
	const rate_ov = (frm.doc.rate_lines || []).filter(rl =>
		Math.round((rl.working_rate || 0) * 100) / 100 !==
		Math.round((rl.fetched_rate || 0) * 100) / 100
	);
	const proc_ov = (frm.doc.processing_lines || []).filter(pl =>
		pl.fetched_charge_per_kg &&
		Math.round((pl.working_charge_per_kg || 0) * 100) / 100 !==
		Math.round((pl.fetched_charge_per_kg || 0) * 100) / 100
	);

	const make_row = (label, fetched, working, reason, attrs) => {
		const delta = fetched ? ((working - fetched) / fetched * 100).toFixed(1) : "—";
		const up = (working || 0) > (fetched || 0);
		return `<tr>
			<td>${frappe.utils.escape_html(label)}</td>
			<td class="text-right">₹${(fetched || 0).toFixed(2)}</td>
			<td class="text-right">₹${(working || 0).toFixed(2)}</td>
			<td class="text-right font-weight-bold" style="color:${up ? "#c62828" : "#2e7d32"}">
				${up ? "↑" : "↓"}${Math.abs(parseFloat(delta)).toFixed(1)}%
			</td>
			<td class="text-muted small">${frappe.utils.escape_html(reason || "")}</td>
			<td><button class="btn btn-xs btn-default" ${attrs}>${__("Revert")}</button></td>
		</tr>`;
	};

	const rows =
		rate_ov.map(rl => make_row(
			rl.item_name || rl.item,
			rl.fetched_rate, rl.working_rate,
			rl.override_reason,
			`data-revert-item="${frappe.utils.escape_html(rl.item)}"`
		)).join("") +
		proc_ov.map(pl => make_row(
			pl.processor || __("Processing"),
			pl.fetched_charge_per_kg, pl.working_charge_per_kg,
			pl.override_reason,
			`data-revert-processing="1"`
		)).join("");

	const html = `
		<table class="table table-sm table-bordered mb-0">
			<thead class="thead-light">
				<tr>
					<th>${__("Item / Charge")}</th>
					<th class="text-right">${__("Market")}</th>
					<th class="text-right">${__("Working")}</th>
					<th class="text-right">Δ</th>
					<th>${__("Reason")}</th>
					<th></th>
				</tr>
			</thead>
			<tbody>${rows}</tbody>
		</table>`;

	const d = new frappe.ui.Dialog({
		title: __(`Active Overrides (${rate_ov.length + proc_ov.length})`),
		fields: [{ fieldtype: "HTML", fieldname: "content" }],
		primary_action_label: __("Revert All"),
		primary_action() {
			frappe.call({
				method: `${API}.revert_all_overrides`,
				args: { pricing_calculation_name: frm.doc.name },
				callback() { d.hide(); frm.reload_doc(); },
			});
		},
	});

	const $w = d.fields_dict.content.$wrapper;
	$w.html(html);

	$w.on("click", "[data-revert-item]", function () {
		const item = $(this).data("revert-item");
		frappe.call({
			method: `${API}.revert_rate_override`,
			args: { pricing_calculation_name: frm.doc.name, item },
			callback() { d.hide(); frm.reload_doc(); },
		});
	});

	$w.on("click", "[data-revert-processing]", function () {
		frappe.call({
			method: `${API}.revert_all_overrides`,
			args: { pricing_calculation_name: frm.doc.name },
			callback() { d.hide(); frm.reload_doc(); },
		});
	});

	d.show();
}

// ─── Freight promote-to-master dialog ───────────────────────────────────────

function _show_freight_promote_dialog(frm, overridden_lines) {
	const rows = overridden_lines.map(dl => {
		const dest = frappe.utils.escape_html(dl.destination_city || dl.destination_address || "—");
		const mode = frappe.utils.escape_html(dl.transport_mode || "Barrels");
		const freshness_badge = dl.rate_freshness === "Missing"
			? `<span class="badge badge-danger">${__("Missing")}</span>`
			: `<span class="badge badge-warning">${__("Override")}</span>`;
		return `<tr>
			<td>${dest}</td>
			<td>${mode}</td>
			<td class="text-right">₹${(dl.working_freight_per_kg || 0).toFixed(4)}/kg</td>
			<td>${freshness_badge}</td>
		</tr>`;
	}).join("");

	const html = `
		<p class="text-muted small mb-2">
			${__("These freight rates will be saved as draft Freight Rate records. Review and submit them to make them active for future calculations.")}
		</p>
		<table class="table table-sm table-bordered mb-0">
			<thead class="thead-light">
				<tr>
					<th>${__("Destination")}</th>
					<th>${__("Mode")}</th>
					<th class="text-right">${__("Rate Used")}</th>
					<th>${__("Status")}</th>
				</tr>
			</thead>
			<tbody>${rows}</tbody>
		</table>
		<div id="freight-promote-result" class="mt-2"></div>`;

	const d = new frappe.ui.Dialog({
		title: __("Save Freight Rates to Master"),
		fields: [{ fieldtype: "HTML", fieldname: "content" }],
		primary_action_label: __("Create Draft Freight Rate(s)"),
		primary_action() {
			d.set_primary_action(__("Creating…"), null);
			frappe.call({
				method: `${API}.promote_freight_overrides_to_master`,
				args: { pricing_calculation_name: frm.doc.name },
				callback(r) {
					const res = r.message || {};
					const created = res.created || [];
					const skipped = res.skipped || [];

					let msg = "";
					if (created.length) {
						const links = created.map(c =>
							`<a href="/app/freight-rate/${encodeURIComponent(c.name)}" target="_blank">${frappe.utils.escape_html(c.name)}</a>`
						).join(", ");
						msg += `<div class="text-success mb-1">✓ ${__("Created")}: ${links}</div>`;
					}
					if (skipped.length) {
						msg += `<div class="text-muted small">${__("Skipped (draft already exists)")}:
							${skipped.map(s => frappe.utils.escape_html(s)).join(", ")}</div>`;
					}
					if (!created.length && !skipped.length) {
						msg = `<div class="text-muted">${__("Nothing to promote — ensure the processor has a Dispatch Address set.")}</div>`;
					}

					d.fields_dict.content.$wrapper.find("#freight-promote-result").html(msg);
					d.set_primary_action(__("Done"), () => { d.hide(); frm.reload_doc(); });
				},
			});
		},
	});

	d.fields_dict.content.$wrapper.html(html);
	d.show();
}

// ─── Combination cards ───────────────────────────────────────────────────────

function _load_and_render_combinations(frm) {
	const raw = _parse_raw(frm.doc.costing_raw);
	_render_combinations(frm, raw.combinations || [], raw);
}

function _render_combinations(frm, combinations, raw) {
	const $wrapper = frm.fields_dict.combinations_html.$wrapper;
	$wrapper.empty();

	const is_submitted = frm.doc.docstatus === 1;

	if (!combinations || !combinations.length) {
		$wrapper.html(`<div class="text-muted p-4">${__("Evaluating formulations…")}</div>`);
		return;
	}

	// Approved read-only banner
	if (is_submitted) {
		$wrapper.append(`
			<div class="p-2 mb-2 border rounded small font-weight-bold text-success" style="background:#e8f5e9;border-color:#a5d6a7!important;">
				✓ ${__("APPROVED — Locked. This costing cannot be modified.")}
			</div>
		`);
	}

	// Switch alert (draft/working only)
	if (!is_submitted && frm.doc.formulation_switch_alert) {
		const cheapest = combinations.find(c => c.rank === 1);
		const preferred = combinations.find(c => c.is_preferred);
		$wrapper.append(`
			<div class="alert alert-warning mb-2 p-2 border border-warning rounded small">
				<strong>⚠ ${__("Formulation switch recommended")}</strong> — ${frappe.utils.escape_html(frm.doc.formulation_switch_alert)}
				<span class="ml-2">
					${cheapest ? `<button class="btn btn-xs btn-primary" onclick="pcSwitchFormulation('${frm.doc.name}', '${cheapest.bom}')">${__("Switch")}</button>` : ""}
					${preferred ? `<button class="btn btn-xs btn-secondary ml-1" onclick="pcKeepFormulation()">${__("Keep current")}</button>` : ""}
				</span>
			</div>
		`);
	}

	const has_prev = combinations.some(c => (c.prev_rm_cost_per_kg || 0) > 0);
	const has_selling = combinations.some(c => (c.selling_price_per_kg || 0) > (c.total_cost_per_kg || 0));

	// Table header
	const select_col_header = is_submitted ? "" : `<th style="width:100px"></th>`;
	const prev_col_header = has_prev ? `<th class="text-right" style="width:110px">${__("Prev RM/kg")}</th>` : "";
	const selling_col_header = has_selling ? `<th class="text-right" style="width:120px">${__("Selling Price/kg")}</th>` : "";
	const rows = [...combinations]
		.sort((a, b) => (a.rank || 99) - (b.rank || 99))
		.map(combo => {
			const is_selected = combo.is_selected;
			const is_excluded = combo.status === "Excluded — Too Expensive";
			const is_cheapest = combo.rank === 1 && !is_excluded;
			const is_prev = combo.is_preferred;

			// Row background — priority: selected > cheapest+prev > cheapest > prev > plain
			let row_bg = "";
			if (is_selected)              row_bg = "background:#e3f2fd;";
			else if (is_cheapest && is_prev) row_bg = "background:#c8e6c9;";
			else if (is_cheapest)          row_bg = "background:#e8f5e9;";
			else if (is_prev)              row_bg = "background:#fff8e1;";

			// Badges in Formulation ID cell
			const badges = [];
			if (is_selected)              badges.push(`<span class="badge badge-primary ml-1">✓ ${__("Selected")}</span>`);
			if (is_cheapest && is_prev)   badges.push(`<span class="badge badge-success ml-1">★ ${__("Cheapest + Previously Used")}</span>`);
			else if (is_cheapest)         badges.push(`<span class="badge badge-success ml-1">★ ${__("Cheapest")}</span>`);
			else if (is_prev)             badges.push(`<span class="badge" style="background:#f9a825;color:#fff;" class="ml-1">★ ${__("Previously Used")}</span>`);

			const status_badge = {
				"Ready to Quote":              `<span class="badge badge-success">${__("Ready")}</span>`,
				"Indicative — Rates Expired":  `<span class="badge badge-warning">${__("Rates Expired")}</span>`,
				"Indicative — Rates Missing":  `<span class="badge badge-danger">${__("Rates Missing")}</span>`,
				"Excluded — Too Expensive":    `<span class="badge badge-secondary">${__("Too Expensive")} +${(combo.delta_pct || 0).toFixed(1)}%</span>`,
			}[combo.status] || `<span class="badge badge-light">${combo.status}</span>`;

			const desc = combo.formulation_description
				? frappe.utils.escape_html(combo.formulation_description)
				: `<span class="text-muted">—</span>`;

			// Prev RM cost cell with delta
			let prev_cell = "";
			if (has_prev) {
				const prev = combo.prev_rm_cost_per_kg || 0;
				if (prev > 0) {
					const current = combo.rm_cost_per_kg || 0;
					const delta = prev > 0 ? ((current - prev) / prev) * 100 : 0;
					const dir = delta >= 0 ? "↑" : "↓";
					const color = delta > 0 ? "color:#c62828;" : "color:#2e7d32;";
					prev_cell = `<td class="text-right small">
						₹${prev.toFixed(2)}<br>
						<span style="${color}">${dir}${Math.abs(delta).toFixed(1)}%</span>
					</td>`;
				} else {
					prev_cell = `<td class="text-right text-muted small">—</td>`;
				}
			}

			const action_cell = is_submitted ? "" : `<td>
				${is_selected
					? `<button class="btn btn-sm btn-success" disabled>✓ ${__("Selected")}</button>`
					: `<button class="btn btn-sm btn-outline-primary" onclick="pcSelectCombination('${frm.doc.name}', '${combo.bom}')">${__("Select")}</button>`
				}
			</td>`;

			const selling_cell = has_selling
				? `<td class="text-right font-weight-bold" style="color:#1565c0;">₹${(combo.selling_price_per_kg || 0).toFixed(2)}</td>`
				: "";

			return `<tr style="${row_bg}">
				<td class="font-weight-bold">${frappe.utils.escape_html(combo.formulation_id || combo.bom)}${badges.join("")}</td>
				<td class="text-muted small">${desc}</td>
				<td class="text-right">₹${(combo.rm_cost_per_kg || 0).toFixed(2)}</td>
				${prev_cell}
				<td class="text-right">₹${(combo.total_cost_per_kg || 0).toFixed(2)}</td>
				${selling_cell}
				<td>${status_badge}</td>
				${action_cell}
			</tr>`;
		}).join("");

	$wrapper.append(`
		<table class="table table-sm table-bordered mb-2">
			<thead class="thead-light">
				<tr>
					<th>${__("Formulation")}</th>
					<th>${__("Description")}</th>
					<th class="text-right" style="width:100px">${__("RM Cost/kg")}</th>
					${prev_col_header}
					<th class="text-right" style="width:110px">${__("Total/kg")}</th>
					${selling_col_header}
					<th style="width:145px">${__("Status")}</th>
					${select_col_header}
				</tr>
			</thead>
			<tbody>${rows}</tbody>
		</table>
	`);

	// Legend
	const legend_items = [
		`<span class="mr-3"><span style="display:inline-block;width:12px;height:12px;background:#c8e6c9;border:1px solid #aaa;vertical-align:middle;" class="mr-1"></span>${__("Cheapest + Previously Used")}</span>`,
		`<span class="mr-3"><span style="display:inline-block;width:12px;height:12px;background:#e8f5e9;border:1px solid #aaa;vertical-align:middle;" class="mr-1"></span>${__("Cheapest")}</span>`,
		`<span class="mr-3"><span style="display:inline-block;width:12px;height:12px;background:#fff8e1;border:1px solid #aaa;vertical-align:middle;" class="mr-1"></span>${__("Previously Used")}</span>`,
		`<span class="mr-3"><span style="display:inline-block;width:12px;height:12px;background:#e3f2fd;border:1px solid #aaa;vertical-align:middle;" class="mr-1"></span>${__("Selected")}</span>`,
	];
	$wrapper.append(`<div class="small text-muted mb-2">${legend_items.join("")}</div>`);

	// Common costs footer
	const ref = combinations[0];
	if (ref) {
		const proc = ref.processing_cost_per_kg || 0;
		const add = ref.additional_charges_per_kg || 0;
		const freight = ref.outward_freight_per_kg || 0;
		$wrapper.append(`
			<div class="p-2 bg-light border rounded small text-muted mb-2">
				<strong class="text-dark">${__("Common to all formulations")}:</strong>
				&nbsp;${__("Processing")} ₹${proc.toFixed(2)}/kg
				· ${__("Additional charges")} ₹${add.toFixed(2)}/kg
				· ${__("Outward freight")} ₹${freight.toFixed(2)}/kg
			</div>
		`);
	}

	// Unified cost snapshot — works for both draft (selected) and submitted
	const snap_combo = combinations.find(c => c.is_selected)
		|| combinations.find(c => frm.doc.selected_combination && c.bom === frm.doc.selected_combination);
	if (snap_combo) {
		const snap_l = {
			...snap_combo,
			additional_charges: raw.additional_charges || [],
			customer_credit_rate_pct: raw.customer_credit_rate_pct,
			credit_days: raw.credit_days,
			solids_content_pct: raw.solids_content_pct,
		};
		_render_cost_snapshot(snap_l, $wrapper);
	}
}

// ─── Unified cost snapshot (draft selected + submitted) ──────────────────────

function _render_cost_snapshot(l, $wrapper) {
	if (!l) return;

	const uid = (l.formulation_id || l.bom || "").replace(/[^a-zA-Z0-9]/g, "_");

	// ── RM ingredient rows (shown inside collapsible) ─────────────────────────
	const sorted_ml = [...(l.material_lines || [])].sort(
		(a, b) => Math.abs(b.amount_per_kg || 0) - Math.abs(a.amount_per_kg || 0)
	);
	const ml_rows = sorted_ml.map(ml => {
		const is_scrap = ml.is_scrap;
		const amount_fmt = is_scrap
			? `<span class="text-success">−₹${Math.abs(ml.amount_per_kg || 0).toFixed(2)}</span>`
			: `₹${(ml.amount_per_kg || 0).toFixed(2)}`;
		const override_note = (!is_scrap && ml.is_overridden)
			? ` <span class="text-warning" title="${__("Override active")}">⚠</span>`
			: "";
		return `<tr>
			<td class="pl-3">${frappe.utils.escape_html(ml.item_name || ml.item)}${override_note}${is_scrap ? ' <em class="text-muted small">(scrap credit)</em>' : ""}</td>
			<td class="text-right text-muted small">${(ml.qty_per_kg_output || 0).toFixed(4)} × ₹${(ml.working_rate || 0).toFixed(2)}</td>
			<td class="text-right">${amount_fmt}/kg</td>
		</tr>`;
	}).join("");

	// ── Totals for each component ─────────────────────────────────────────────
	const rm       = l.rm_cost_per_kg || 0;
	const proc     = l.processing_cost_per_kg || 0;
	const addl     = l.additional_charges_per_kg
		|| (l.additional_charges || []).reduce((s, c) => s + (c.amount_per_kg || 0), 0)
		|| 0;
	const pkg      = l.packaging_cost_per_kg || 0;
	const freight  = l.outward_freight_per_kg || l.freight_total_per_kg || 0;
	const margin   = l.margin_per_kg || 0;
	const comm     = l.commission_per_kg || 0;
	const credit   = l.credit_charge_per_kg || 0;
	const selling  = l.selling_price_per_kg || 0;
	const has_selling = selling > 0;

	const proc_detail = l.solids_content_pct && proc
		? ` <span class="text-muted small">(${l.solids_content_pct}% solids)</span>`
		: "";

	// ── Build table body rows with running total ──────────────────────────────
	let running = 0;
	let tbody = "";

	const _row = (label, value, extra_style) => {
		running += value;
		return `<tr${extra_style ? ` style="${extra_style}"` : ""}>
			<td style="padding:3px 8px;">${label}</td>
			<td class="text-right" style="padding:3px 8px;">₹${value.toFixed(2)}/kg</td>
			<td class="text-right text-muted" style="padding:3px 8px;border-left:1px solid #e0e0e0;">₹${running.toFixed(2)}</td>
		</tr>`;
	};

	// RM Cost row — clickable, toggles ingredient detail
	running += rm;
	tbody += `<tr style="cursor:pointer;" onclick="(function(){
		var d=document.getElementById('rmdet_${uid}');
		d.classList.toggle('d-none');
		document.getElementById('rmico_${uid}').textContent=d.classList.contains('d-none')?'▶':'▼';
	})()">
		<td style="padding:3px 8px;"><span id="rmico_${uid}">▶</span> <strong>${__("RM Cost")}</strong> <span class="text-muted small">${__("(click to expand)")}</span></td>
		<td class="text-right" style="padding:3px 8px;">₹${rm.toFixed(2)}/kg</td>
		<td class="text-right text-muted" style="padding:3px 8px;border-left:1px solid #e0e0e0;">₹${running.toFixed(2)}</td>
	</tr>
	<tr id="rmdet_${uid}" class="d-none" style="background:#f9fbe7;">
		<td colspan="3" class="p-0">
			<table class="table table-sm mb-0" style="font-size:11px;">
				<thead class="thead-light">
					<tr>
						<th class="pl-3">${__("Ingredient")}</th>
						<th class="text-right">${__("Qty × Rate")}</th>
						<th class="text-right">${__("Amount/kg")}</th>
					</tr>
				</thead>
				<tbody>${ml_rows}</tbody>
				<tfoot>
					<tr class="thead-light">
						<td colspan="2" class="text-right font-weight-bold">${__("RM Total")}</td>
						<td class="text-right font-weight-bold">₹${rm.toFixed(2)}/kg</td>
					</tr>
				</tfoot>
			</table>
		</td>
	</tr>`;

	tbody += _row(`${__("Processing")}${proc_detail}`, proc);
	if (addl)    tbody += _row(__("Additional Charges"), addl);
	if (pkg)     tbody += _row(__("Packaging"), pkg);
	if (freight) tbody += _row(__("Freight"), freight);

	if (has_selling) {
		if (margin) tbody += _row(__("Margin"), margin);
		if (comm)   tbody += _row(__("Commission"), comm);
		if (credit) tbody += _row(`${__("Credit Charge")} <span class="text-muted small">(${l.credit_days || 0}d @ ${l.customer_credit_rate_pct || 0}% pa)</span>`, credit);
		tbody += `<tr style="background:#e3f2fd;border-top:2px solid #1565c0;">
			<td class="font-weight-bold" style="padding:4px 8px;color:#1565c0;">${__("Selling Price")}</td>
			<td class="text-right font-weight-bold" style="padding:4px 8px;color:#1565c0;">₹${selling.toFixed(2)}/kg</td>
			<td style="padding:4px 8px;border-left:1px solid #e0e0e0;"></td>
		</tr>`;
	}

	// ── Rate overrides section ────────────────────────────────────────────────
	const rate_overrides = (l.material_lines || []).filter(ml => ml.is_overridden && !ml.is_scrap);
	let overrides_html = "";
	if (rate_overrides.length) {
		const or_rows = rate_overrides.map(ml => {
			const diff_pct = ml.fetched_rate
				? ((ml.working_rate - ml.fetched_rate) / ml.fetched_rate * 100).toFixed(1)
				: "—";
			const up = (ml.working_rate || 0) > (ml.fetched_rate || 0);
			return `<tr>
				<td>${frappe.utils.escape_html(ml.item_name || ml.item)}</td>
				<td class="text-right">₹${(ml.fetched_rate || 0).toFixed(2)}</td>
				<td class="text-right">₹${(ml.working_rate || 0).toFixed(2)}</td>
				<td class="text-right font-weight-bold" style="color:${up ? "#c62828" : "#2e7d32"}">
					${up ? "↑" : "↓"}${Math.abs(parseFloat(diff_pct)).toFixed(1)}%
				</td>
				<td class="text-muted small">${frappe.utils.escape_html(ml.override_reason || "")}</td>
			</tr>`;
		}).join("");
		overrides_html = `
			<div class="font-weight-bold mt-3 mb-1 pt-2 border-top" style="color:#e65100;">
				⚠ ${__("Rate Overrides")} (${rate_overrides.length})
			</div>
			<table class="table table-sm table-bordered mb-0" style="font-size:12px;">
				<thead class="thead-light">
					<tr>
						<th>${__("Item")}</th>
						<th class="text-right">${__("Market Rate")}</th>
						<th class="text-right">${__("Used Rate")}</th>
						<th class="text-right">${__("Change")}</th>
						<th>${__("Reason")}</th>
					</tr>
				</thead>
				<tbody>${or_rows}</tbody>
			</table>`;
	} else {
		overrides_html = `<div class="text-muted small mt-2 pt-2 border-top">✓ ${__("No rate overrides — all market rates used.")}</div>`;
	}

	$wrapper.append(`
		<div class="border rounded p-3 mt-2" style="background:#fafafa;">
			<div class="font-weight-bold mb-2" style="font-size:1.05em;">
				━━ ${__("COST SNAPSHOT")} — ${frappe.utils.escape_html(l.formulation_id || l.bom)} ━━
			</div>
			<table class="table table-sm mb-0" style="font-size:12px;">
				<thead>
					<tr style="border-bottom:1px solid #bdbdbd;">
						<th style="padding:3px 8px;min-width:180px;">${__("Component")}</th>
						<th class="text-right" style="padding:3px 8px;width:110px;">${__("Amount/kg")}</th>
						<th class="text-right text-muted" style="padding:3px 8px;width:120px;border-left:1px solid #e0e0e0;">${__("Running Total")}</th>
					</tr>
				</thead>
				<tbody>${tbody}</tbody>
			</table>
			${overrides_html}
		</div>
	`);
}

window.pcSelectCombination = function(pc_name, bom) {
	frappe.call({
		method: `${API}.select_combination`,
		args: { pricing_calculation_name: pc_name, bom: bom },
		callback(r) {
			if (r.message) {
				frappe.show_alert({ message: __("Formulation selected"), indicator: "green" });
				cur_frm.reload_doc();
			}
		},
	});
};

window.pcSwitchFormulation = function(pc_name, bom) {
	pcSelectCombination(pc_name, bom);
};

window.pcKeepFormulation = function() {
	frappe.show_alert({ message: __("Keeping current formulation"), indicator: "blue" });
};


// ─── MD approval banner ──────────────────────────────────────────────────────

function _render_approval_banner(frm) {
	const raw = _parse_raw(frm.doc.costing_raw);
	const combo = (raw.combinations || []).find(c => c.bom === frm.doc.selected_combination);
	const overrides = (combo?.material_lines || []).filter(ml => ml.is_overridden && !ml.is_scrap);

	const override_lines = overrides.map(ml => {
		const diff_pct = ml.fetched_rate
			? (((ml.working_rate - ml.fetched_rate) / ml.fetched_rate) * 100).toFixed(1)
			: "—";
		return `· ${ml.item_name || ml.item}: ₹${(ml.fetched_rate || 0).toFixed(2)} → ₹${(ml.working_rate || 0).toFixed(2)} (${diff_pct}%)`;
	}).join("<br>");

	frm.dashboard.add_comment(`
		<strong>READY TO QUOTE</strong><br>
		Selected: ${frm.doc.selected_combination || "—"}<br>
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
}

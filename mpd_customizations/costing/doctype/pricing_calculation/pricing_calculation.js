// Pricing Calculation — costing team form
// Internal use only. No sales-facing logic here.

const API = "mpd_customizations.costing.api.costing";

let _config_production_days = null;
let _config_financing_rate = null;
let _pending_fetch_result = null;
let _evaluate_timer = null;
const _auto_evaluated = new Set();  // tracks which PC names have been synced this session

// ─── Initialisation ─────────────────────────────────────────────────────────

frappe.ui.form.on("Pricing Calculation", {
	onload(_frm) {
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
			const ex = frm.doc.confirmed_ex_factory_cost_per_kg;
			const sp = frm.doc.confirmed_selling_price_per_kg;
			const label = (sp && sp > ex)
				? `Ex-Factory: ₹${ex.toFixed(2)}/kg &nbsp;·&nbsp; <strong>Selling: ₹${sp.toFixed(2)}/kg</strong>`
				: `Ex-Factory: ₹${ex.toFixed(2)}/kg`;
			frm.dashboard.add_comment(label, "blue", true);
		}

		if ((frm.doc.mode === "Ready to Quote" || frm.doc.mode === "Approved") && frappe.user.has_role("Costing Approver")) {
			_render_approval_banner(frm);
		}

		_load_and_render_combinations(frm);
		// Breakdown panel only shown for draft docs — submitted docs get full snapshot in combinations_html
		if (frm.doc.selected_combination && frm.doc.docstatus === 0) {
			_load_and_render_breakdown(frm);
		}

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
		_schedule_evaluate(frm);
	},

	supplier_financing_rate_pct(frm) {
		_apply_amber_indicators(frm);
		_schedule_evaluate(frm);
	},

	solids_content_pct(frm) {
		_schedule_evaluate(frm);
	},

	preferred_bom(frm) {
		_schedule_evaluate(frm);
	},

	additional_charges_remove(frm) {
		_schedule_evaluate(frm);
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

// ─── Costing Additional Charge child table ───────────────────────────────────

frappe.ui.form.on("Costing Additional Charge", {
	rate(frm) { _schedule_evaluate(frm); },
	basis(frm) { _schedule_evaluate(frm); },
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

// ─── Reactive recompute ───────────────────────────────────────────────────────

function _schedule_evaluate(frm) {
	if (frm.doc.__islocal) return;
	clearTimeout(_evaluate_timer);
	_evaluate_timer = setTimeout(() => {
		if (frm.is_dirty()) {
			frm.save().then(() => _do_evaluate(frm));
		} else {
			_do_evaluate(frm);
		}
	}, 600);
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
					${cheapest ? `<button class="btn btn-xs btn-primary" onclick="pcSwitchFormulation('${frm.doc.name}', '${cheapest.name}')">${__("Switch")}</button>` : ""}
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
					: `<button class="btn btn-sm btn-outline-primary" onclick="pcSelectCombination('${frm.doc.name}', '${combo.name}')">${__("Select")}</button>`
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
					<th class="text-right" style="width:110px">${has_selling ? __("Ex-Factory/kg") : __("Total/kg")}</th>
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
		const fin = ref.financing_cost_per_kg || 0;
		$wrapper.append(`
			<div class="p-2 bg-light border rounded small text-muted mb-2">
				<strong class="text-dark">${__("Common to all formulations")}:</strong>
				&nbsp;${__("Financing")} ₹${fin.toFixed(2)}/kg
				· ${__("Processing")} ₹${proc.toFixed(2)}/kg
				· ${__("Additional charges")} ₹${add.toFixed(2)}/kg
				· ${__("Outward freight")} ₹${freight.toFixed(2)}/kg
			</div>
		`);
	}

	// Overrides summary — draft/working only
	if (!is_submitted) {
		const overrides = (frm.doc.rate_lines || []).filter(rl =>
			Math.round((rl.working_rate || 0) * 100) / 100 !==
			Math.round((rl.fetched_rate || 0) * 100) / 100
		);
		if (overrides.length) {
			const override_spans = overrides.map(rl => {
				const diff_pct = rl.fetched_rate
					? (((rl.working_rate - rl.fetched_rate) / rl.fetched_rate) * 100).toFixed(1)
					: "—";
				const dir = (rl.working_rate || 0) > (rl.fetched_rate || 0) ? "↑" : "↓";
				return `<span class="mr-3">${frappe.utils.escape_html(rl.item_name || rl.item)}: ₹${(rl.fetched_rate || 0).toFixed(2)} → ₹${(rl.working_rate || 0).toFixed(2)} <strong>${dir}${Math.abs(parseFloat(diff_pct)).toFixed(1)}%</strong></span>`;
			}).join("");
			$wrapper.append(`
				<div class="p-2 border rounded small" style="background:#fff8e1;border-color:#ffc107!important;">
					<strong>⚠ ${overrides.length} rate override${overrides.length > 1 ? "s" : ""} active:</strong>
					<div class="mt-1">${override_spans}</div>
				</div>
			`);
		}
	}

	// Submitted: load and append the full approved cost snapshot
	if (is_submitted && frm.doc.selected_combination) {
		frappe.call({
			method: `${API}.get_cost_breakdown`,
			args: { pricing_calculation_name: frm.doc.name },
			callback(r) {
				if (r.message) _render_approved_cost_snapshot(frm, r.message, $wrapper);
			},
		});
	}
}

// ─── Approved cost snapshot (rendered inside combinations_html when submitted) ──

function _render_approved_cost_snapshot(frm, data, $wrapper) {
	const l = data.layer1;
	if (!l) return;

	// ── RM Materials table ────────────────────────────────────────────────────
	const sorted_ml = [...(l.material_lines || [])].sort(
		(a, b) => Math.abs(b.amount_per_kg || 0) - Math.abs(a.amount_per_kg || 0)
	);
	const ml_rows = sorted_ml.map(ml => {
		const is_scrap = ml.is_scrap;
		const amount_fmt = is_scrap
			? `<span class="text-success">−₹${Math.abs(ml.amount_per_kg || 0).toFixed(2)}</span>`
			: `₹${(ml.amount_per_kg || 0).toFixed(2)}`;
		const overridden = !is_scrap && ml.is_overridden;
		const override_note = overridden
			? ` <span class="text-warning" title="Override active">⚠</span>`
			: "";
		return `<tr class="${is_scrap ? "table-success" : ""}">
			<td>${frappe.utils.escape_html(ml.item_name || ml.item)}${override_note}${is_scrap ? ' <em class="text-muted small">(scrap credit)</em>' : ""}</td>
			<td class="text-right text-muted small">${(ml.qty_per_kg_output || 0).toFixed(4)}</td>
			<td class="text-right">₹${(ml.working_rate || 0).toFixed(2)}</td>
			<td class="text-right font-weight-bold">${amount_fmt}/kg</td>
		</tr>`;
	}).join("");

	// ── Additional charges rows ───────────────────────────────────────────────
	const add_rows = (l.additional_charges || []).map(c =>
		`<tr>
			<td>${frappe.utils.escape_html(c.description)} <span class="text-muted small">(${c.basis})</span></td>
			<td colspan="2"></td>
			<td class="text-right">₹${(c.amount_per_kg || 0).toFixed(2)}/kg</td>
		</tr>`
	).join("");

	// ── Variable costs summary block ──────────────────────────────────────────
	const proc_detail = l.solids_content_pct && l.processing_cost_per_kg
		? `${l.solids_content_pct}% solids × ₹${(l.processing_cost_per_kg / (l.solids_content_pct / 100) || 0).toFixed(2)}/kg`
		: "";

	// ── Rate overrides audit table ────────────────────────────────────────────
	const rate_overrides = (frm.doc.rate_lines || []).filter(rl =>
		rl.fetched_rate && Math.round((rl.working_rate || 0) * 100) / 100 !== Math.round(rl.fetched_rate * 100) / 100
	);
	const proc_overrides = (frm.doc.processing_lines || []).filter(pl =>
		pl.fetched_charge_per_kg && Math.round((pl.working_charge_per_kg || 0) * 100) / 100 !== Math.round(pl.fetched_charge_per_kg * 100) / 100
	);

	let overrides_html = "";
	if (rate_overrides.length || proc_overrides.length) {
		const rate_override_rows = rate_overrides.map(rl => {
			const diff_pct = ((rl.working_rate - rl.fetched_rate) / rl.fetched_rate * 100).toFixed(1);
			const up = rl.working_rate > rl.fetched_rate;
			return `<tr>
				<td>${frappe.utils.escape_html(rl.item_name || rl.item)}</td>
				<td>${__("Material Rate")}</td>
				<td class="text-right">₹${(rl.fetched_rate || 0).toFixed(2)}</td>
				<td class="text-right">₹${(rl.working_rate || 0).toFixed(2)}</td>
				<td class="text-right font-weight-bold" style="color:${up ? "#c62828" : "#2e7d32"}">
					${up ? "↑" : "↓"}${Math.abs(parseFloat(diff_pct)).toFixed(1)}%
				</td>
				<td class="text-muted small">${frappe.utils.escape_html(rl.override_reason || "")}</td>
			</tr>`;
		}).join("");

		const proc_override_rows = proc_overrides.map(pl => {
			const diff_pct = ((pl.working_charge_per_kg - pl.fetched_charge_per_kg) / pl.fetched_charge_per_kg * 100).toFixed(1);
			const up = pl.working_charge_per_kg > pl.fetched_charge_per_kg;
			return `<tr>
				<td>${frappe.utils.escape_html(pl.processor || __("Processing"))}</td>
				<td>${__("Processing Charge")}</td>
				<td class="text-right">₹${(pl.fetched_charge_per_kg || 0).toFixed(2)}</td>
				<td class="text-right">₹${(pl.working_charge_per_kg || 0).toFixed(2)}</td>
				<td class="text-right font-weight-bold" style="color:${up ? "#c62828" : "#2e7d32"}">
					${up ? "↑" : "↓"}${Math.abs(parseFloat(diff_pct)).toFixed(1)}%
				</td>
				<td class="text-muted small">${frappe.utils.escape_html(pl.override_reason || "")}</td>
			</tr>`;
		}).join("");

		overrides_html = `
			<div class="font-weight-bold mt-3 mb-1 pt-2 border-top">${__("Rate Overrides")} (${rate_overrides.length + proc_overrides.length})</div>
			<table class="table table-sm table-bordered mb-0">
				<thead class="thead-light">
					<tr>
						<th>${__("Item / Charge")}</th>
						<th>${__("Type")}</th>
						<th class="text-right">${__("Market Rate")}</th>
						<th class="text-right">${__("Used Rate")}</th>
						<th class="text-right">${__("Change")}</th>
						<th>${__("Reason")}</th>
					</tr>
				</thead>
				<tbody>${rate_override_rows}${proc_override_rows}</tbody>
			</table>`;
	} else {
		overrides_html = `<div class="text-muted small mt-2 pt-2 border-top">✓ ${__("No rate overrides — all market rates used as-is.")}</div>`;
	}

	$wrapper.append(`
		<div class="border rounded p-3 mt-3" style="background:#fafafa;">
			<div class="font-weight-bold mb-2" style="font-size:1.05em;">
				━━ ${__("APPROVED COST SNAPSHOT")} — ${frappe.utils.escape_html(l.formulation_id || l.bom)} ━━
			</div>

			<div class="font-weight-bold mb-1">${__("Raw Materials")}</div>
			<table class="table table-sm table-bordered mb-2">
				<thead class="thead-light">
					<tr>
						<th>${__("Ingredient")}</th>
						<th class="text-right" style="width:90px">${__("Qty/kg out")}</th>
						<th class="text-right" style="width:100px">${__("Rate used")}</th>
						<th class="text-right" style="width:110px">${__("Amount/kg")}</th>
					</tr>
				</thead>
				<tbody>${ml_rows}</tbody>
				<tfoot>
					<tr class="thead-light">
						<td colspan="3" class="text-right font-weight-bold">${__("RM Cost")}</td>
						<td class="text-right font-weight-bold">₹${(l.rm_cost_per_kg || 0).toFixed(2)}/kg</td>
					</tr>
				</tfoot>
			</table>

			<div class="font-weight-bold mb-1">${__("Variable Costs")}</div>
			<table class="table table-sm table-bordered mb-2">
				<tbody>
					<tr>
						<td>${__("RM Financing")} <span class="text-muted small">(${l.supplier_financing_rate_pct}% pa, ${Math.max(0, l.production_days - 60)}d beyond 60d)</span></td>
						<td class="text-right" style="width:130px">₹${(l.financing_cost_per_kg || 0).toFixed(2)}/kg</td>
					</tr>
					<tr>
						<td>${__("Processing")}${proc_detail ? ` <span class="text-muted small">(${proc_detail})</span>` : ""}</td>
						<td class="text-right">₹${(l.processing_cost_per_kg || 0).toFixed(2)}/kg</td>
					</tr>
					${add_rows}
					<tr>
						<td>${__("Outward Freight")}</td>
						<td class="text-right">₹${(l.outward_freight_per_kg || 0).toFixed(2)}/kg</td>
					</tr>
					<tr class="thead-light">
						<td class="font-weight-bold">${__("CONFIRMED EX-FACTORY COST")}</td>
						<td class="text-right font-weight-bold" style="font-size:1.1em;">₹${(l.total_cost_per_kg || 0).toFixed(2)}/kg</td>
					</tr>
					${(l.selling_price_per_kg || 0) > (l.total_cost_per_kg || 0) ? `
					<tr>
						<td>${__("Credit Charge")} <span class="text-muted small">(${l.credit_days || 0}d, ${Math.max(0, (l.credit_days || 0) - 30)} extra days @ ${l.customer_credit_rate_pct || 0}% pa)</span></td>
						<td class="text-right">₹${(l.credit_charge_per_kg || 0).toFixed(2)}/kg</td>
					</tr>
					<tr>
						<td>${__("Commission")}</td>
						<td class="text-right">₹${(l.commission_per_kg || 0).toFixed(2)}/kg</td>
					</tr>
					<tr>
						<td>${__("Margin")}</td>
						<td class="text-right">₹${(l.margin_per_kg || 0).toFixed(2)}/kg</td>
					</tr>
					<tr style="background:#e3f2fd;">
						<td class="font-weight-bold">${__("SELLING PRICE")}</td>
						<td class="text-right font-weight-bold" style="font-size:1.1em;color:#1565c0;">₹${(l.selling_price_per_kg || 0).toFixed(2)}/kg</td>
					</tr>` : ""}
				</tbody>
			</table>

			${overrides_html}
		</div>
	`);
}

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
			${(l.selling_price_per_kg || 0) > (l.total_cost_per_kg || 0) ? `
			<hr>
			<div class="font-weight-bold mt-2">CUSTOMER PRICING</div>
			<div class="ml-3">Credit Charge <span class="text-muted small">(${l.credit_days || 0} days, ${Math.max(0, (l.credit_days || 0) - 30)} extra days @ ${l.customer_credit_rate_pct || 0}% pa)</span> — ₹${(l.credit_charge_per_kg || 0).toFixed(2)}/kg</div>
			<div class="ml-3">Commission — ₹${(l.commission_per_kg || 0).toFixed(2)}/kg</div>
			<div class="ml-3">Margin — ₹${(l.margin_per_kg || 0).toFixed(2)}/kg</div>
			<hr>
			<div class="font-weight-bold" style="color:#1565c0;">SELLING PRICE: ₹${(l.selling_price_per_kg || 0).toFixed(2)}/kg</div>
			` : ""}
		</div>
	`);
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

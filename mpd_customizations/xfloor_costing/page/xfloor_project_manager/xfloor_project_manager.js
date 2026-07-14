frappe.pages["xfloor-project-manager"].on_page_load = function (wrapper) {
	frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Xfloor Project Manager"),
		single_column: true,
	});

	const page = wrapper.page;
	const $root = $(frappe.render_template("xfloor_project_manager", {})).appendTo(page.main);
	const state = {
		projects: [],
		active: null,
		activeTab: "input",
		preview: null,
	};

	const COMPONENTS = ["Top coat", "Screed", "Primer", "Coving", "Hi-build"];
	const COAT_OPTS = ["0", "500 micron", "1mm", "2mm"];
	const PRINT_FORMAT = "Floor Project P&L";

	const fmt = (v) => format_currency(v || 0, "INR");
	const fmtN = (v) => Math.round(v || 0).toLocaleString("en-IN");
	const fmtD = (v) => (Math.round((v || 0) * 100) / 100).toFixed(2);

	const defaultPart = (name) => ({
		part_name: name || "Main",
		sqft: 0,
		top_coat_option: "1mm",
		screed_option: "1mm",
		applicator_rate: 0,
	});

	const ensureParts = (p) => {
		if (!p.parts || !p.parts.length) {
			p.parts = [
				defaultPart(
					p.project_number || "Main"
				),
			];
			if (p.sqft) p.parts[0].sqft = p.sqft;
			if (p.top_coat_option) p.parts[0].top_coat_option = p.top_coat_option;
			if (p.screed_option) p.parts[0].screed_option = p.screed_option;
			if (p.applicator_rate) p.parts[0].applicator_rate = p.applicator_rate;
		}
		return p.parts;
	};

	const totalSqft = (p) =>
		(ensureParts(p) || []).reduce((a, part) => a + flt(part.sqft), 0);

	const collectPayload = () => {
		const p = state.active;
		if (!p) return null;
		const $c = $root.find("#xfloor-tab-content");
		const parts = ensureParts(p).map((part) => ({
			part_name: part.part_name || "Main",
			sqft: flt(part.sqft),
			top_coat_option: part.top_coat_option || "1mm",
			screed_option: part.screed_option || "1mm",
			applicator_rate: flt(part.applicator_rate),
		}));
		return {
			name: p.name,
			party_name: $c.find("#xf_party_name").val() || p.party_name,
			rate_per_sqft: flt($c.find("#xf_rate").val()),
			coving_kits: flt($c.find("#xf_coving").val()),
			hibuild_kits: flt($c.find("#xf_hibuild").val()),
			parts,
			dispatch_lines: p.dispatch_lines || [],
		};
	};

	const renderSidebar = () => {
		const el = $root.find("#xfloor-project-list").empty();
		if (!state.projects.length) {
			el.append(`<div class="text-muted small" style="opacity:.5">${__("No projects yet")}</div>`);
			return;
		}
		state.projects.forEach((p) => {
			const pl = p.profit_loss || 0;
			const active = state.active && state.active.name === p.name ? " active" : "";
			const $item = $(
				`<div class="xfloor-proj-item${active}">
					<div><strong>${frappe.utils.escape_html(p.party_name || p.project_number || p.name)}</strong></div>
					<div class="small" style="opacity:.6">${frappe.utils.escape_html(p.project_number || p.name)}</div>
					<div class="small" style="color:${pl >= 0 ? "#4ade80" : "#f87171"}">${fmt(pl)}</div>
				</div>`
			);
			$item.on("click", () => openProject(p.name));
			el.append($item);
		});
	};

	const renderDashboard = (data) => {
		$root.find("#xfloor-editor").hide();
		$root.find("#xfloor-dashboard").show();
		$root.find("#xfloor-title").text(__("Dashboard"));
		$root.find("#xfloor-badge").hide();

		const totals = data.totals || {};
		$root.find("#xfloor-dashboard").html(
			`<div class="xfloor-kpi">
				<div class="xfloor-kpi-card"><div class="lbl">${__("Total Projects")}</div><div class="val">${(data.projects || []).length}</div></div>
				<div class="xfloor-kpi-card"><div class="lbl">${__("Contract")}</div><div class="val">${fmt(totals.contract_value)}</div></div>
				<div class="xfloor-kpi-card"><div class="lbl">${__("Cost")}</div><div class="val">${fmt(totals.total_cost)}</div></div>
				<div class="xfloor-kpi-card"><div class="lbl">${__("Net P&L")}</div><div class="val ${(totals.profit_loss || 0) >= 0 ? "pos" : "neg"}">${fmt(totals.profit_loss)}</div></div>
			</div>
			<div class="table-responsive">
				<table class="table table-bordered table-sm">
					<thead><tr>
						<th>${__("Project")}</th><th>${__("Sq Ft")}</th>
						<th>${__("Contract")}</th><th>${__("Cost")}</th><th>${__("P&L")}</th><th>${__("Margin")}</th>
					</tr></thead>
					<tbody>
						${(data.projects || [])
							.map((p) => {
								const pl = p.profit_loss || 0;
								return `<tr style="cursor:pointer" data-name="${p.name}">
									<td>${frappe.utils.escape_html(p.party_name || p.project_number || p.name)}</td>
									<td>${fmtN(p.sqft)}</td>
									<td>${fmt(p.contract_value)}</td>
									<td>${fmt(p.total_cost)}</td>
									<td style="color:${pl >= 0 ? "#1e6b3a" : "#a0231c"};font-weight:600">${pl >= 0 ? "+" : ""}${fmt(pl)}</td>
									<td>${flt(p.margin_pct).toFixed(1)}%</td>
								</tr>`;
							})
							.join("")}
					</tbody>
				</table>
			</div>`
		);
		$root.find("#xfloor-dashboard tbody tr").on("click", function () {
			openProject($(this).data("name"));
		});
	};

	const coatCards = (field, selected, partIdx) =>
		COAT_OPTS.map(
			(o) =>
				`<div class="xfloor-opt-card${(selected || "1mm") === o ? " selected" : ""}" data-part-idx="${partIdx}" data-field="${field}" data-val="${o}">
					<div class="opt-label">${o}</div>
				</div>`
		).join("");

	const renderPartCard = (part, idx, canRemove) => {
		const name = frappe.utils.escape_html(part.part_name || `Part ${idx + 1}`);
		return `
			<div class="xfloor-part-card" data-part-idx="${idx}">
				<div class="xfloor-part-header">
					<input class="form-control input-sm xf-part-name" value="${name}" placeholder="${__("Part name")}">
					<div class="xfloor-part-actions">
						<button type="button" class="btn btn-xs btn-default xf-part-dup" title="${__("Duplicate")}">
							<i class="fa fa-copy"></i>
						</button>
						${
							canRemove
								? `<button type="button" class="btn btn-xs btn-danger xf-part-del" title="${__("Remove")}">
							<i class="fa fa-trash"></i>
						</button>`
								: ""
						}
					</div>
				</div>
				<div class="xfloor-grid">
					<div><label>${__("Square Feet")}</label>
						<input type="number" class="form-control input-sm xf-part-sqft" value="${part.sqft || 0}" min="0"></div>
					<div><label>${__("Applicator Rate (per sqft)")}</label>
						<input type="number" class="form-control input-sm xf-part-applicator" value="${part.applicator_rate || 0}" min="0" step="0.5"></div>
				</div>
				<div class="xfloor-section-title" style="margin-top:12px">${__("Top Coat Option")}</div>
				<div class="xfloor-opt-row">${coatCards("top_coat_option", part.top_coat_option, idx)}</div>
				<div class="xfloor-section-title">${__("Screed Option")}</div>
				<div class="xfloor-opt-row">${coatCards("screed_option", part.screed_option, idx)}</div>
			</div>`;
	};

	const renderInputTab = (p) => {
		const parts = ensureParts(p);
		const partCards = parts.map((part, idx) => renderPartCard(part, idx, parts.length > 1)).join("");

		return `
			<div class="xfloor-grid">
				<div><label>${__("Party Name")}</label><input class="form-control input-sm" id="xf_party_name" value="${frappe.utils.escape_html(p.party_name || "")}"></div>
				<div><label>${__("Project Number")}</label><input class="form-control input-sm" id="xf_project_number" value="${frappe.utils.escape_html(p.project_number || p.name || __("Auto on save"))}" disabled></div>
				<div><label>${__("Rate per Sqft")}</label><input type="number" class="form-control input-sm" id="xf_rate" value="${p.rate_per_sqft || 0}"></div>
				<div><label>${__("Total Sq Ft")}</label><input class="form-control input-sm" id="xf_total_sqft" value="${fmtN(totalSqft(p))}" disabled></div>
			</div>
			<div class="xfloor-section-title">${__("Additional Kits")}</div>
			<div class="xfloor-grid">
				<div><label>${__("Coving Kits")}</label><input type="number" class="form-control input-sm" id="xf_coving" value="${p.coving_kits || 0}" min="0"></div>
				<div><label>${__("Hi-build Kits")}</label><input type="number" class="form-control input-sm" id="xf_hibuild" value="${p.hibuild_kits || 0}" min="0"></div>
			</div>
			<div class="xfloor-section-title" style="display:flex;justify-content:space-between;align-items:center">
				<span>${__("Project Parts")}</span>
				<button type="button" class="btn btn-xs btn-primary" id="xf-add-part"><i class="fa fa-plus"></i> ${__("Add Part")}</button>
			</div>
			<div id="xf-parts-list">${partCards}</div>`;
	};

	const renderBudgetTable = (rows, sqft, totalCost, costPerSqft) => {
		const tableRows = (rows || [])
			.map((r) => {
				const cov = r.coverage ? fmtN(r.coverage) : "—";
				const kits =
					r.component === "Applicator"
						? "—"
						: `<span class="xfloor-kit-badge">${fmtN(r.kits)}</span>`;
				const rate =
					r.component === "Applicator" && r.rate
						? `₹${fmtD(r.rate)}/sqft`
						: fmt(r.rate);
				return `<tr>
					<td><strong>${r.component}</strong></td>
					<td>${r.option || "—"}</td>
					<td class="num">${cov}</td>
					<td class="num">${kits}</td>
					<td class="num">${rate}</td>
					<td class="num">${fmt(r.cost)}</td>
					<td class="num">${sqft ? "₹" + fmtD(r.cost_per_sqft) : "—"}</td>
				</tr>`;
			})
			.join("");

		return `
			<div style="overflow-x:auto">
				<table class="xfloor-kit-table">
					<thead><tr>
						<th>${__("Component")}</th><th>${__("Option")}</th>
						<th class="num">${__("Sqft/kit")}</th><th class="num">${__("Kits Required")}</th>
						<th class="num">${__("Rate/kit")}</th><th class="num">${__("Cost")}</th><th class="num">${__("Cost/sqft")}</th>
					</tr></thead>
					<tbody>${tableRows}
						<tr class="total-row">
							<td colspan="5" class="num">${__("Total")}</td>
							<td class="num">${fmt(totalCost)}</td>
							<td class="num">₹${fmtD(costPerSqft)}</td>
						</tr>
					</tbody>
				</table>
			</div>`;
	};

	const renderBudgetTab = (p, rows, partBudgets) => {
		const budgetRows = rows || p.budget_rows || [];
		const partsBudget = partBudgets || p.part_budgets || [];
		const pl = p.profit_loss || 0;
		const sqft = p.sqft || totalSqft(p);

		const partSections = partsBudget
			.map((part) => {
				const s = part.summary || {};
				return `
					<div class="xfloor-part-budget">
						<div class="xfloor-section-title">${frappe.utils.escape_html(part.part_name || __("Part"))}
							<span class="text-muted" style="font-weight:400;text-transform:none;letter-spacing:0">
								· ${fmtN(part.sqft)} sqft
							</span>
						</div>
						${renderBudgetTable(part.budget_rows, part.sqft, s.total_cost, s.cost_per_sqft)}
					</div>`;
			})
			.join("");

		return `
			<div class="xfloor-kpi">
				<div class="xfloor-kpi-card"><div class="lbl">${__("Contract Value")}</div><div class="val">${fmt(p.contract_value)}</div></div>
				<div class="xfloor-kpi-card"><div class="lbl">${__("Total Cost")}</div><div class="val">${fmt(p.total_cost)}</div></div>
				<div class="xfloor-kpi-card"><div class="lbl">${__("Cost per Sqft")}</div><div class="val">₹${fmtD(p.cost_per_sqft)}</div></div>
				<div class="xfloor-kpi-card"><div class="lbl">${__("Margin")}</div><div class="val ${pl >= 0 ? "pos" : "neg"}">${flt(p.margin_pct).toFixed(1)}%</div></div>
			</div>
			${partSections}
			<div class="xfloor-section-title">${__("Project Total")}</div>
			${renderBudgetTable(budgetRows, sqft, p.total_cost, p.cost_per_sqft)}
			<div class="xfloor-pl-banner ${pl >= 0 ? "profit" : "loss"}">
				<div>
					<div class="pl-title">${pl >= 0 ? __("Profit") : __("Loss")}</div>
					<div class="pl-sub">${fmt(p.contract_value)} ${__("contract")} − ${fmt(p.total_cost)} ${__("total cost")}</div>
				</div>
				<div class="pl-num">${pl >= 0 ? "+" : ""}${fmt(pl)}</div>
			</div>`;
	};

	const renderActualTab = (p) => {
		const lines = p.dispatch_lines || [];
		const addBtn = `<div style="margin-bottom:10px"><button class="btn btn-primary btn-sm" id="xf-add-dispatch"><i class="fa fa-plus"></i> ${__("Add Dispatch")}</button></div>`;
		if (!lines.length) {
			return `${addBtn}<div class="xfloor-empty">${__("No dispatches recorded yet.")}</div>`;
		}
		const rows = lines
			.map((row, i) => {
				const opts = COMPONENTS.map(
					(c) => `<option value="${c}"${row.component === c ? " selected" : ""}>${c}</option>`
				).join("");
				return `<tr data-idx="${i}">
					<td><input type="date" class="form-control input-sm xf-dispatch-date" value="${row.dispatch_date || ""}"></td>
					<td><select class="form-control input-sm xf-dispatch-comp">${opts}</select></td>
					<td><input type="number" class="form-control input-sm xf-dispatch-kits" value="${row.kits || 0}" min="0"></td>
					<td><input type="number" class="form-control input-sm xf-dispatch-rate" value="${row.rate_per_kit || 0}" min="0"></td>
					<td class="num xf-dispatch-amt">${fmt((row.kits || 0) * (row.rate_per_kit || 0))}</td>
					<td><button class="btn btn-xs btn-danger xf-dispatch-del"><i class="fa fa-times"></i></button></td>
				</tr>`;
			})
			.join("");

		const totalCost = lines.reduce((a, r) => a + (r.kits || 0) * (r.rate_per_kit || 0), 0);
		return `
			${addBtn}
			<div style="overflow-x:auto">
				<table class="table table-bordered table-sm xfloor-dispatch-table">
					<thead><tr>
						<th>${__("Date")}</th><th>${__("Component")}</th>
						<th>${__("Kits")}</th><th>${__("Rate/kit")}</th><th>${__("Amount")}</th><th></th>
					</tr></thead>
					<tbody>${rows}</tbody>
					<tfoot><tr>
						<td colspan="4" style="font-weight:600">${__("Total Actual Cost")}</td>
						<td class="num" style="font-weight:700" id="xf-dispatch-total">${fmt(totalCost)}</td>
						<td></td>
					</tr></tfoot>
				</table>
			</div>`;
	};

	const renderCompareTab = (p) => {
		if (p.comparison_html) {
			return p.comparison_html;
		}
		return `<div class="xfloor-empty">${__("Save the project and add dispatches to see comparison.")}</div>`;
	};

	const renderActionBar = (p) => {
		$root.find("#xfloor-action-bar").html(`
			<button class="btn btn-danger btn-sm" id="xf-delete">${__("Delete")}</button>
			<button class="btn btn-default btn-sm" id="xf-save">${__("Save")}</button>
			<button class="btn btn-default btn-sm" id="xf-print">${__("Export PDF")}</button>
		`);

		$root.find("#xf-delete").on("click", async () => {
			await frappe.confirm(__("Delete this project?"));
			await frappe.call("mpd_customizations.xfloor_costing.api.pl.delete_project", { name: p.name });
			state.active = null;
			await loadDashboard();
		});

		$root.find("#xf-save").on("click", () => saveProject());
		$root.find("#xf-print").on("click", () => {
			frappe.utils.print("Floor Project", p.name, PRINT_FORMAT);
		});
	};

	const syncPartInputsFromDom = () => {
		const parts = ensureParts(state.active);
		$root.find(".xfloor-part-card").each(function () {
			const idx = $(this).data("part-idx");
			const part = parts[idx];
			if (!part) return;
			part.part_name = $(this).find(".xf-part-name").val() || part.part_name;
			part.sqft = flt($(this).find(".xf-part-sqft").val());
			part.applicator_rate = flt($(this).find(".xf-part-applicator").val());
		});
		$root.find("#xf_total_sqft").val(fmtN(totalSqft(state.active)));
	};

	const bindInputEvents = () => {
		const $c = $root.find("#xfloor-tab-content");

		$c.find(".xfloor-opt-card").on("click", function () {
			const idx = $(this).data("part-idx");
			const field = $(this).data("field");
			const val = $(this).data("val");
			const parts = ensureParts(state.active);
			if (parts[idx]) {
				parts[idx][field] = val;
			}
			$(this).siblings().removeClass("selected");
			$(this).addClass("selected");
			previewCalc();
		});

		$c.find(".xf-part-name, .xf-part-sqft, .xf-part-applicator, #xf_party_name, #xf_rate, #xf_coving, #xf_hibuild").on(
			"change input",
			() => {
				syncPartInputsFromDom();
				previewCalc();
			}
		);

		$c.find("#xf-add-part").on("click", () => {
			syncPartInputsFromDom();
			const parts = ensureParts(state.active);
			parts.push(defaultPart(`Part ${parts.length + 1}`));
			renderTabContent();
			previewCalc();
		});

		$c.find(".xf-part-del").on("click", function () {
			syncPartInputsFromDom();
			const idx = $(this).closest(".xfloor-part-card").data("part-idx");
			const parts = ensureParts(state.active);
			if (parts.length <= 1) return;
			parts.splice(idx, 1);
			renderTabContent();
			previewCalc();
		});

		$c.find(".xf-part-dup").on("click", function () {
			syncPartInputsFromDom();
			const idx = $(this).closest(".xfloor-part-card").data("part-idx");
			const parts = ensureParts(state.active);
			const src = parts[idx];
			if (!src) return;
			parts.splice(idx + 1, 0, {
				...src,
				part_name: `${src.part_name || "Part"} (copy)`,
			});
			renderTabContent();
			previewCalc();
		});
	};

	const bindDispatchEvents = () => {
		const $c = $root.find("#xfloor-tab-content");
		$c.find(".xf-dispatch-date, .xf-dispatch-comp, .xf-dispatch-kits, .xf-dispatch-rate").on(
			"change input",
			function () {
				const $tr = $(this).closest("tr");
				const idx = $tr.data("idx");
				const row = state.active.dispatch_lines[idx];
				if (!row) return;
				row.dispatch_date = $tr.find(".xf-dispatch-date").val();
				row.component = $tr.find(".xf-dispatch-comp").val();
				row.kits = flt($tr.find(".xf-dispatch-kits").val());
				row.rate_per_kit = flt($tr.find(".xf-dispatch-rate").val());
				$tr.find(".xf-dispatch-amt").text(fmt(row.kits * row.rate_per_kit));
				const total = (state.active.dispatch_lines || []).reduce(
					(a, r) => a + (r.kits || 0) * (r.rate_per_kit || 0),
					0
				);
				$c.find("#xf-dispatch-total").text(fmt(total));
			}
		);
		$c.find(".xf-dispatch-del").on("click", function () {
			const idx = $(this).closest("tr").data("idx");
			state.active.dispatch_lines.splice(idx, 1);
			renderEditor(state.active);
		});
	};

	const renderTabContent = () => {
		const p = state.active;
		if (!p) return;
		const $content = $root.find("#xfloor-tab-content");
		const tab = state.activeTab;

		if (tab === "input") {
			$content.html(renderInputTab(p));
			bindInputEvents();
		} else if (tab === "budget") {
			const rows = state.preview ? state.preview.budget_rows : p.budget_rows;
			const partBudgets = state.preview ? state.preview.part_budgets : p.part_budgets;
			const summary = state.preview ? state.preview.summary : null;
			const display = summary
				? { ...p, ...summary, budget_rows: rows, part_budgets: partBudgets }
				: p;
			$content.html(renderBudgetTab(display, rows, partBudgets));
		} else if (tab === "actual") {
			$content.html(renderActualTab(p));
			bindDispatchEvents();
		} else if (tab === "compare") {
			$content.html(renderCompareTab(p));
		}
	};

	const renderEditor = (project) => {
		ensureParts(project);
		$root.find("#xfloor-dashboard").hide();
		$root.find("#xfloor-editor").show();
		$root.find("#xfloor-title").text(project.party_name || project.project_number || __("New Project"));
		const badge = $root.find("#xfloor-badge");
		if (project.project_number) {
			badge.text(project.project_number).show();
		} else {
			badge.hide();
		}

		$root.find(".xfloor-tab").removeClass("active");
		$root.find(`.xfloor-tab[data-tab="${state.activeTab}"]`).addClass("active");

		renderTabContent();
		renderActionBar(project);
		renderSidebar();
	};

	const previewCalc = frappe.utils.debounce(async () => {
		if (state.activeTab === "input") {
			syncPartInputsFromDom();
		}
		const payload = collectPayload();
		if (!payload) return;
		const sqft = (payload.parts || []).reduce((a, part) => a + flt(part.sqft), 0);
		if (!sqft) return;
		const r = await frappe.call("mpd_customizations.xfloor_costing.api.pl.calc_project", {
			data: payload,
		});
		state.preview = r.message;
		if (state.activeTab === "budget") {
			renderTabContent();
		}
	}, 400);

	const saveProject = async () => {
		if (state.activeTab === "input") {
			syncPartInputsFromDom();
		}
		const payload = collectPayload();
		if (!payload) return;
		const r = await frappe.call("mpd_customizations.xfloor_costing.api.pl.save_project", {
			doc: payload,
		});
		state.active = r.message;
		state.preview = null;
		frappe.show_alert({ message: __("Saved"), indicator: "green" });
		await loadDashboard();
		renderEditor(state.active);
	};

	const openProject = async (name) => {
		const r = await frappe.call("mpd_customizations.xfloor_costing.api.pl.get_project", { name });
		state.active = r.message;
		state.preview = null;
		state.activeTab = state.activeTab || "input";
		renderEditor(state.active);
	};

	const updateSettingsButtons = (data) => {
		$root.find("#xfloor-open-kit-rates").toggle(!!data?.can_view_rates);
		$root.find("#xfloor-open-kit-coverage").toggle(
			frappe.user.has_role("System Manager") ||
				frappe.user.has_role("XFloor Costing Manager") ||
				frappe.session.user === "Administrator"
		);
	};

	const loadDashboard = async () => {
		const r = await frappe.call("mpd_customizations.xfloor_costing.api.pl.get_dashboard");
		state.projects = r.message.projects || [];
		updateSettingsButtons(r.message);
		renderSidebar();
		renderDashboard(r.message);
	};

	$root.find("#xfloor-new-project").on("click", async () => {
		const r = await frappe.call("mpd_customizations.xfloor_costing.api.pl.save_project", {
			doc: {
				status: "Draft",
				parts: [defaultPart("Main")],
			},
		});
		state.activeTab = "input";
		state.active = r.message;
		await loadDashboard();
		renderEditor(state.active);
	});

	$root.find("#xfloor-show-dashboard").on("click", async () => {
		state.active = null;
		state.preview = null;
		await loadDashboard();
	});

	$root.find("#xfloor-open-kit-rates").on("click", () => {
		frappe.set_route("Form", "Kit rates", "Kit rates");
	});

	$root.find("#xfloor-open-kit-coverage").on("click", () => {
		frappe.set_route("Form", "Kit Coverage", "Kit Coverage");
	});

	$root.find("#xfloor-tabs").on("click", ".xfloor-tab", function () {
		if (state.activeTab === "input") {
			syncPartInputsFromDom();
		}
		state.activeTab = $(this).data("tab");
		$root.find(".xfloor-tab").removeClass("active");
		$(this).addClass("active");
		if (state.activeTab === "actual" && state.active && !(state.active.dispatch_lines || []).length) {
			state.active.dispatch_lines = [
				{ dispatch_date: "", component: "Top coat", kits: 0, rate_per_kit: 0 },
			];
		}
		renderTabContent();
		if (state.activeTab === "budget") {
			previewCalc();
		}
	});

	$root.on("click", "#xf-add-dispatch", () => {
		if (!state.active.dispatch_lines) state.active.dispatch_lines = [];
		state.active.dispatch_lines.push({
			dispatch_date: "",
			component: "Top coat",
			kits: 0,
			rate_per_kit: 0,
		});
		renderTabContent();
	});

	loadDashboard();
};

import frappe
from frappe import _
from frappe.model.document import Document

from mpd_customizations.xfloor_costing.services.pl_engine import (
	build_comparison,
	calc_project,
	flat_fields_to_main_part,
)


class FloorProject(Document):
	def before_insert(self):
		self._assign_project_number()

	def validate(self):
		self._assign_project_number()
		self._ensure_main_part()
		self._validate_numbers()
		self._sync_rollup_fields()
		self._set_dispatch_amounts()
		self._recalculate_budget()

	def _assign_project_number(self):
		"""Project Number follows DocType autoname (XFP-.YYYY.-.#####)."""
		if self.name and self.name != "new-floor-project":
			self.project_number = self.name

	def get_budget_rows(self):
		data = frappe.parse_json(self.budget_json or "[]")
		if isinstance(data, dict):
			return data.get("rows") or []
		return data or []

	def get_part_budgets(self):
		data = frappe.parse_json(self.budget_json or "[]")
		if isinstance(data, dict):
			return data.get("parts") or []
		return []

	def get_comparison_rows(self):
		return frappe.parse_json(self.comparison_json or "[]")

	def before_print(self, print_settings=None):
		self.budget_rows = self.get_budget_rows()
		self.part_budgets = self.get_part_budgets()
		self.kit_rates = frappe.get_single("Kit rates")

	def _ensure_main_part(self):
		"""Safety net: migrate flat inputs into a single Main part when parts is empty."""
		if self.get("parts"):
			return

		has_flat = (
			(self.sqft or 0) > 0
			or self.top_coat_option
			or self.screed_option
			or (self.applicator_rate or 0) > 0
		)
		if not has_flat:
			self.append(
				"parts",
				{
					"part_name": "Main",
					"sqft": 0,
					"top_coat_option": "1mm",
					"screed_option": "1mm",
					"applicator_rate": 0,
				},
			)
			return

		part = flat_fields_to_main_part(
			{
				"sqft": self.sqft,
				"top_coat_option": self.top_coat_option,
				"screed_option": self.screed_option,
				"applicator_rate": self.applicator_rate,
			}
		)
		self.append("parts", part)

	def _validate_numbers(self):
		for fieldname in ("rate_per_sqft", "coving_kits", "hibuild_kits"):
			if (self.get(fieldname) or 0) < 0:
				frappe.throw(_("{0} cannot be negative.").format(self.meta.get_label(fieldname)))

		if not self.get("parts"):
			frappe.throw(_("At least one project part is required."))

		for row in self.parts:
			if (row.sqft or 0) < 0:
				frappe.throw(_("Part Square Feet cannot be negative."))
			if (row.applicator_rate or 0) < 0:
				frappe.throw(_("Part Applicator Rate cannot be negative."))
			if not (row.part_name or "").strip():
				frappe.throw(_("Part Name is required for every part."))

	def _sync_rollup_fields(self):
		parts = self.get("parts") or []
		self.sqft = sum(float(p.sqft or 0) for p in parts)
		if not parts:
			self.top_coat_option = self.top_coat_option or "1mm"
			self.screed_option = self.screed_option or "1mm"
			self.applicator_rate = self.applicator_rate or 0
			return

		first = parts[0]
		options = {p.top_coat_option or "1mm" for p in parts}
		screeds = {p.screed_option or "1mm" for p in parts}
		rates = {float(p.applicator_rate or 0) for p in parts}
		# Select fields cannot store "mixed"; use sole value or first part for list view.
		self.top_coat_option = next(iter(options)) if len(options) == 1 else (first.top_coat_option or "1mm")
		self.screed_option = next(iter(screeds)) if len(screeds) == 1 else (first.screed_option or "1mm")
		self.applicator_rate = next(iter(rates)) if len(rates) == 1 else 0

	def _set_dispatch_amounts(self):
		for row in self.dispatch_lines or []:
			row.amount = (row.kits or 0) * (row.rate_per_kit or 0)

	def _recalculate_budget(self):
		result = calc_project(self)
		summary = result["summary"]

		self.contract_value = summary["contract_value"]
		self.total_cost = summary["total_cost"]
		self.profit_loss = summary["profit_loss"]
		self.margin_pct = summary["margin_pct"]
		self.cost_per_sqft = summary["cost_per_sqft"]
		self.budget_json = frappe.as_json(
			{
				"rows": result["budget_rows"],
				"parts": result.get("part_budgets") or [],
			}
		)

		comparison = build_comparison(result["budget_rows"], self.dispatch_lines or [])
		self.comparison_json = frappe.as_json(comparison)
		self.comparison_html = _comparison_to_html(comparison)


def _comparison_to_html(rows):
	if not rows:
		return "<p class='text-muted'>No comparison available.</p>"
	html_rows = "".join(
		f"""
		<tr>
			<td>{row['component']}</td>
			<td style='text-align:right'>{row['budget_kits']:.2f}</td>
			<td style='text-align:right'>{row['actual_kits']:.2f}</td>
			<td style='text-align:right'>{row['budget_cost']:.2f}</td>
			<td style='text-align:right'>{row['actual_cost']:.2f}</td>
			<td style='text-align:right'>{row['variance_cost']:.2f}</td>
		</tr>
		"""
		for row in rows
	)
	return f"""
	<div style="overflow-x:auto">
	<table class="table table-bordered small">
		<thead>
			<tr>
				<th>Component</th>
				<th style='text-align:right'>Budget Kits</th>
				<th style='text-align:right'>Actual Kits</th>
				<th style='text-align:right'>Budget Cost</th>
				<th style='text-align:right'>Actual Cost</th>
				<th style='text-align:right'>Variance Cost</th>
			</tr>
		</thead>
		<tbody>{html_rows}</tbody>
	</table>
	</div>
	"""

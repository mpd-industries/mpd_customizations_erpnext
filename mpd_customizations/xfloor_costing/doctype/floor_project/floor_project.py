import frappe
from frappe import _
from frappe.model.document import Document

from mpd_customizations.xfloor_costing.services.pl_engine import build_comparison, calc_project


class FloorProject(Document):
	def validate(self):
		self._validate_numbers()
		self._set_dispatch_amounts()
		self._recalculate_budget()

	def get_budget_rows(self):
		return frappe.parse_json(self.budget_json or "[]")

	def get_comparison_rows(self):
		return frappe.parse_json(self.comparison_json or "[]")

	def before_print(self, print_settings=None):
		self.budget_rows = self.get_budget_rows()
		self.kit_rates = frappe.get_single("Kit rates")

	def _validate_numbers(self):
		for fieldname in ("sqft", "rate_per_sqft", "coving_kits", "hibuild_kits", "applicator_rate"):
			if (self.get(fieldname) or 0) < 0:
				frappe.throw(_("{0} cannot be negative.").format(self.meta.get_label(fieldname)))

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
		self.budget_json = frappe.as_json(result["budget_rows"])

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

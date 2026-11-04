# Copyright (c) 2026, mpdindustries and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import today

COVERAGE_FIELDS = (
	"top_coat_500_coverage",
	"top_coat_1mm_coverage",
	"top_coat_2mm_coverage",
	"top_coat_3mm_coverage",
	"top_coat_4mm_coverage",
	"pu_top_coat_1mm_coverage",
	"pu_top_coat_2mm_coverage",
	"pu_top_coat_3mm_coverage",
	"pu_top_coat_4mm_coverage",
	"screed_500_coverage",
	"screed_1mm_coverage",
	"screed_2mm_coverage",
	"screed_3mm_coverage",
	"screed_4mm_coverage",
	"screed_5mm_coverage",
	"screed_6mm_coverage",
	"screed_7mm_coverage",
	"primer_coverage",
	"coving_coverage",
)


class KitCoverage(Document):
	def validate(self):
		for fieldname in COVERAGE_FIELDS:
			if (self.get(fieldname) or 0) <= 0:
				frappe.throw(f"{self.meta.get_label(fieldname)} must be greater than 0.")

		self._capture_revision_history()

	def _capture_revision_history(self):
		if self.is_new():
			return

		prev = self.get_doc_before_save()
		if not prev:
			return

		coverage_changed = any(
			float(prev.get(fieldname) or 0) != float(self.get(fieldname) or 0)
			for fieldname in COVERAGE_FIELDS
		)
		if not coverage_changed:
			return

		self.append(
			"coverage_revisions",
			{
				"effective_date": prev.coverage_effective_date or today(),
				**{fieldname: prev.get(fieldname) for fieldname in COVERAGE_FIELDS},
			},
		)
		if not self.coverage_effective_date:
			self.coverage_effective_date = today()

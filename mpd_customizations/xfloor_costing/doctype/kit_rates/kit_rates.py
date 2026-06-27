# Copyright (c) 2026, mpdindustries and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import today

RATE_FIELDS = (
	"top_coat_rate",
	"screed_rate",
	"primer_rate",
	"hibuild_rate",
	"coving_rate",
)


class Kitrates(Document):
	def validate(self):
		for fieldname in RATE_FIELDS:
			if (self.get(fieldname) or 0) <= 0:
				frappe.throw(f"{self.meta.get_label(fieldname)} must be greater than 0.")

		self._capture_revision_history()

	def _capture_revision_history(self):
		if self.is_new():
			return

		prev = self.get_doc_before_save()
		if not prev:
			return

		rates_changed = any(
			float(prev.get(fieldname) or 0) != float(self.get(fieldname) or 0)
			for fieldname in RATE_FIELDS
		)
		if not rates_changed:
			return

		self.append(
			"rate_revisions",
			{
				"effective_date": prev.rates_effective_date or today(),
				**{fieldname: prev.get(fieldname) for fieldname in RATE_FIELDS},
			},
		)
		if not self.rates_effective_date:
			self.rates_effective_date = today()

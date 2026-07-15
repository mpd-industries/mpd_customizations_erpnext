# Copyright (c) 2026, mpdindustries and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import today

RATE_FIELDS = (
	"top_coat_rate",
	"pu_top_coat_rate",
	"screed_rate",
	"primer_rate",
	"hibuild_rate",
	"coving_rate",
)

GM_FIELDS = (
	"top_coat_gm",
	"pu_top_coat_gm",
	"screed_gm",
	"primer_gm",
	"hibuild_gm",
	"coving_gm",
)

TRACKED_FIELDS = RATE_FIELDS + GM_FIELDS


class Kitrates(Document):
	def before_print(self, print_settings=None):
		from mpd_customizations.xfloor_costing.services.pl_engine import (
			build_price_list,
			get_kit_rates_doc,
		)

		settings = get_kit_rates_doc()
		self.price_list = build_price_list(settings)
		self.kit_coverage = frappe.get_single("Kit Coverage")

	def validate(self):
		for fieldname in RATE_FIELDS:
			if (self.get(fieldname) or 0) <= 0:
				frappe.throw(f"{self.meta.get_label(fieldname)} must be greater than 0.")

		if (self.get("default_applicator_rate") or 0) < 0:
			frappe.throw(f"{self.meta.get_label('default_applicator_rate')} cannot be negative.")

		for fieldname in GM_FIELDS:
			if (self.get(fieldname) or 0) < 0:
				frappe.throw(f"{self.meta.get_label(fieldname)} cannot be negative.")

		self._capture_revision_history()

	def _capture_revision_history(self):
		if self.is_new():
			return

		prev = self.get_doc_before_save()
		if not prev:
			return

		changed = any(
			float(prev.get(fieldname) or 0) != float(self.get(fieldname) or 0)
			for fieldname in TRACKED_FIELDS
		)
		if not changed:
			return

		self.append(
			"rate_revisions",
			{
				"effective_date": prev.rates_effective_date or today(),
				**{fieldname: prev.get(fieldname) for fieldname in TRACKED_FIELDS},
			},
		)
		if not self.rates_effective_date:
			self.rates_effective_date = today()

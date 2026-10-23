import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

_FETCHER_FRAPPE = "mpd_customizations.costing.services.rate_fetcher.frappe"


def _make_doc(item="PAINT-001", processor="PROC-001"):
	doc = MagicMock()
	doc.item = item
	doc.processor = processor
	doc.production_days = 30
	doc.supplier_financing_rate_pct = 12.0
	doc.rate_lines = []
	doc.processing_lines = []

	def _append(fieldname, data):
		target = doc.rate_lines if fieldname == "rate_lines" else doc.processing_lines
		target.append(dict(data) if isinstance(data, dict) else data)

	doc.append.side_effect = _append
	return doc


def _make_rate_line(item, fetched=100.0, working=100.0, credit=30, fetched_credit=30, freshness="Current"):
	rl = MagicMock()
	rl.item = item
	rl.fetched_rate = fetched
	rl.working_rate = working
	rl.fetched_supplier_credit_days = fetched_credit
	rl.working_supplier_credit_days = credit
	rl.rate_freshness = freshness
	rl.supplier = "SUP-001"
	rl.rate_source_ref = "MR-001"
	return rl


def _make_rate_option(item="MAT-001", city="Indore", rate=105.0, freshness="Current", credit=30):
	from mpd_customizations.costing.services.rate_option import RateOption
	return RateOption(
		item=item,
		city=city,
		delivered_rate=rate,
		valid_from=datetime.now(),
		rate_freshness=freshness,
		supplier="SUP-001",
		rate_source_ref="MR-002",
		supplier_credit_days=credit,
	)


class TestRateFetcher(unittest.TestCase):

	def test_preserve_overrides_keeps_working_values(self):
		from mpd_customizations.costing.services.rate_fetcher import RateFetcher

		doc = _make_doc()
		existing_rl = _make_rate_line("MAT-001", fetched=100.0, working=120.0, credit=30, fetched_credit=30)
		doc.rate_lines = [existing_rl]

		with patch(_FETCHER_FRAPPE) as mock_frappe, \
		     patch("mpd_customizations.costing.services.rate_fetcher.get_default_registry") as mock_reg, \
		     patch("mpd_customizations.costing.services.rate_fetcher._get_processing_charge", return_value=None), \
		     patch("mpd_customizations.costing.services.rate_fetcher.now_datetime", return_value=datetime.now()):

			mock_frappe.db.get_value.return_value = "Indore"
			mock_frappe.get_all.side_effect = [
				[{"name": "BOM-001", "item": "PAINT-001", "quantity": 1, "custom_formulation_id": "F1"}],
				[{"parent": "BOM-001", "item_code": "MAT-001", "item_name": "M1", "qty": 0.5, "uom": "Kg"}],
			]
			mock_frappe._.side_effect = lambda x, *a: x
			mock_frappe._dict = dict

			registry = MagicMock()
			registry.batch_resolve.return_value = {("MAT-001", "Indore"): _make_rate_option(rate=105.0)}
			mock_reg.return_value = registry

			result = RateFetcher.fetch(doc, preserve_overrides=True)

		# fetched updated, working preserved
		self.assertEqual(existing_rl.fetched_rate, 105.0)
		self.assertEqual(existing_rl.working_rate, 120.0)
		self.assertTrue(result.overrides_detected)
		self.assertIn("MAT-001", result.overrides_changed)

	def test_reset_mode_sets_working_to_fetched(self):
		from mpd_customizations.costing.services.rate_fetcher import RateFetcher

		doc = _make_doc()
		existing_rl = _make_rate_line("MAT-001", fetched=100.0, working=120.0)
		doc.rate_lines = [existing_rl]

		with patch(_FETCHER_FRAPPE) as mock_frappe, \
		     patch("mpd_customizations.costing.services.rate_fetcher.get_default_registry") as mock_reg, \
		     patch("mpd_customizations.costing.services.rate_fetcher._get_processing_charge", return_value=None), \
		     patch("mpd_customizations.costing.services.rate_fetcher.now_datetime", return_value=datetime.now()):

			mock_frappe.db.get_value.return_value = "Indore"
			mock_frappe.get_all.side_effect = [
				[{"name": "BOM-001", "item": "PAINT-001", "quantity": 1, "custom_formulation_id": "F1"}],
				[{"parent": "BOM-001", "item_code": "MAT-001", "item_name": "M1", "qty": 0.5, "uom": "Kg"}],
			]
			mock_frappe._.side_effect = lambda x, *a: x
			mock_frappe._dict = dict

			registry = MagicMock()
			registry.batch_resolve.return_value = {("MAT-001", "Indore"): _make_rate_option(rate=108.0)}
			mock_reg.return_value = registry

			RateFetcher.fetch(doc, preserve_overrides=False)

		self.assertEqual(existing_rl.working_rate, 108.0)
		self.assertEqual(existing_rl.fetched_rate, 108.0)

	def test_new_bom_item_added_to_rate_lines(self):
		from mpd_customizations.costing.services.rate_fetcher import RateFetcher

		doc = _make_doc()
		doc.rate_lines = []

		with patch(_FETCHER_FRAPPE) as mock_frappe, \
		     patch("mpd_customizations.costing.services.rate_fetcher.get_default_registry") as mock_reg, \
		     patch("mpd_customizations.costing.services.rate_fetcher._get_processing_charge", return_value=None), \
		     patch("mpd_customizations.costing.services.rate_fetcher.now_datetime", return_value=datetime.now()):

			mock_frappe.db.get_value.return_value = "Indore"
			mock_frappe.get_all.side_effect = [
				[{"name": "BOM-001", "item": "PAINT-001", "quantity": 1, "custom_formulation_id": "F1"}],
				[{"parent": "BOM-001", "item_code": "MAT-NEW", "item_name": "New", "qty": 0.3, "uom": "Kg"}],
			]
			mock_frappe._.side_effect = lambda x, *a: x
			mock_frappe._dict = dict

			registry = MagicMock()
			registry.batch_resolve.return_value = {
				("MAT-NEW", "Indore"): _make_rate_option(item="MAT-NEW", rate=50.0, credit=15)
			}
			mock_reg.return_value = registry

			RateFetcher.fetch(doc, preserve_overrides=True)

		self.assertEqual(len(doc.rate_lines), 1)
		new_line = doc.rate_lines[0]
		self.assertEqual(new_line["working_rate"], 50.0)
		self.assertEqual(new_line["fetched_rate"], 50.0)

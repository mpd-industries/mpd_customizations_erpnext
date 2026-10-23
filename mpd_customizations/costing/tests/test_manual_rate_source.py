import unittest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from mpd_customizations.costing.services.sources.manual_rate_source import ManualRateSource

_MODULE = "mpd_customizations.costing.services.sources.manual_rate_source.frappe"


def _dt(days_offset=0):
	return datetime(2024, 6, 15, 12, 0, 0) + timedelta(days=days_offset)


PRICING_DT = _dt(0)


def _record(item="MAT-001", city="Indore", supplier="SUP-001", delivered=100.0,
             credit=30, valid_from_offset=-10, valid_to_offset=20, rate_type="All-In Delivered",
             ex_works=None, name="MR-0001", lead_time=None):
	return {
		"name": name,
		"item": item,
		"city": city,
		"supplier": supplier,
		"delivered_rate": delivered,
		"credit_days": credit,
		"lead_time_days": lead_time,
		"valid_from": _dt(valid_from_offset),
		"valid_to": _dt(valid_to_offset),
		"rate_type": rate_type,
		"ex_works_rate": ex_works,
		"uom": "Kg",
	}


class TestManualRateSource(unittest.TestCase):
	def setUp(self):
		self.source = ManualRateSource()

	def test_current_rate_selected_over_expired(self):
		current = _record(delivered=100.0, valid_from_offset=-5, valid_to_offset=10, name="MR-001")
		expired = _record(delivered=80.0, valid_from_offset=-30, valid_to_offset=-5, name="MR-002")

		with patch(_MODULE) as mock_frappe:
			mock_frappe.get_all.return_value = [current, expired]
			result = self.source.batch_resolve([("MAT-001", "Indore")], PRICING_DT)

		options = result[("MAT-001", "Indore")]
		self.assertEqual(options[0].rate_freshness, "Current")
		self.assertEqual(options[0].delivered_rate, 100.0)

	def test_cheapest_current_wins(self):
		r1 = _record(delivered=120.0, name="MR-001")
		r2 = _record(delivered=90.0, name="MR-002")
		r3 = _record(delivered=110.0, name="MR-003")

		with patch(_MODULE) as mock_frappe:
			mock_frappe.get_all.return_value = [r1, r2, r3]
			result = self.source.batch_resolve([("MAT-001", "Indore")], PRICING_DT)

		options = result[("MAT-001", "Indore")]
		self.assertEqual(options[0].delivered_rate, 90.0)

	def test_expired_fallback_when_no_current(self):
		expired = _record(delivered=80.0, valid_from_offset=-30, valid_to_offset=-5, name="MR-001")

		with patch(_MODULE) as mock_frappe:
			mock_frappe.get_all.return_value = [expired]
			result = self.source.batch_resolve([("MAT-001", "Indore")], PRICING_DT)

		options = result[("MAT-001", "Indore")]
		self.assertEqual(options[0].rate_freshness, "Expired")

	def test_missing_placeholder_when_no_records(self):
		with patch(_MODULE) as mock_frappe:
			mock_frappe.get_all.return_value = []
			result = self.source.batch_resolve([("MAT-001", "Indore")], PRICING_DT)

		options = result[("MAT-001", "Indore")]
		self.assertEqual(options[0].rate_freshness, "Missing")
		self.assertEqual(options[0].delivered_rate, 0.0)

	def test_confidence_score_all_in_delivered_no_breakup(self):
		r = _record(rate_type="All-In Delivered", ex_works=None, name="MR-001")
		with patch(_MODULE) as mock_frappe:
			mock_frappe.get_all.return_value = [r]
			result = self.source.batch_resolve([("MAT-001", "Indore")], PRICING_DT)

		score = result[("MAT-001", "Indore")][0].confidence_score
		self.assertLessEqual(score, 50.0)

	def test_batch_resolve_multiple_pairs_one_call(self):
		r1 = _record(item="MAT-001", city="Indore", name="MR-001")
		r2 = _record(item="MAT-002", city="Indore", supplier="SUP-002", name="MR-002")
		call_count = [0]

		def mock_get_all(*args, **kwargs):
			call_count[0] += 1
			return [r1, r2]

		with patch(_MODULE) as mock_frappe:
			mock_frappe.get_all.side_effect = mock_get_all
			result = self.source.batch_resolve(
				[("MAT-001", "Indore"), ("MAT-002", "Indore")], PRICING_DT
			)

		self.assertEqual(call_count[0], 1)
		self.assertIn(("MAT-001", "Indore"), result)
		self.assertIn(("MAT-002", "Indore"), result)

	def test_second_best_populated(self):
		r1 = _record(supplier="SUP-001", delivered=90.0, name="MR-001")
		r2 = _record(supplier="SUP-002", delivered=100.0, name="MR-002")

		with patch(_MODULE) as mock_frappe:
			mock_frappe.get_all.return_value = [r1, r2]
			result = self.source.batch_resolve([("MAT-001", "Indore")], PRICING_DT)

		best = result[("MAT-001", "Indore")][0]
		self.assertEqual(best.second_best_supplier, "SUP-002")
		self.assertEqual(best.second_best_rate, 100.0)

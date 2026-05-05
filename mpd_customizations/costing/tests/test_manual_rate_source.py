import unittest
from unittest.mock import patch
from datetime import datetime
from frappe.utils.data import get_datetime
from mpd_customizations.costing.services.sources.manual_rate_source import ManualRateSource

class DummyRecord:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

class TestManualRateSource(unittest.TestCase):
    @patch("frappe.get_all")
    def test_cheapest_current_rate_wins(self, mock_get_all):
        mock_get_all.return_value = [
            DummyRecord(name="MR1", item="A", city="C1", supplier="S1", delivered_rate=100.0, 
                        is_active=1, valid_from="2023-01-01 00:00:00", valid_to=None, rate_type="All-In Delivered", ex_works_rate=0, credit_days=30, lead_time_days=5),
            DummyRecord(name="MR2", item="A", city="C1", supplier="S2", delivered_rate=90.0, 
                        is_active=1, valid_from="2023-01-01 00:00:00", valid_to=None, rate_type="All-In Delivered", ex_works_rate=0, credit_days=30, lead_time_days=5)
        ]
        source = ManualRateSource()
        pricing_dt = datetime(2023, 6, 1)
        res = source.resolve("A", "C1", pricing_dt)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].supplier, "S2")
        self.assertEqual(res[0].delivered_rate, 90.0)
        self.assertEqual(res[0].rate_freshness, "Current")
        self.assertEqual(res[0].second_best_supplier, "S1")
        self.assertEqual(res[0].second_best_rate, 100.0)

    @patch("frappe.get_all")
    def test_expired_fallback(self, mock_get_all):
        mock_get_all.return_value = [
            DummyRecord(name="MR1", item="A", city="C1", supplier="S1", delivered_rate=100.0, 
                        is_active=1, valid_from="2022-01-01 00:00:00", valid_to="2022-12-31 23:59:59", rate_type="All-In Delivered", ex_works_rate=0, credit_days=30, lead_time_days=5),
        ]
        source = ManualRateSource()
        pricing_dt = datetime(2023, 6, 1)
        res = source.resolve("A", "C1", pricing_dt)
        self.assertEqual(res[0].rate_freshness, "Expired")
        self.assertEqual(res[0].delivered_rate, 100.0)

    @patch("frappe.get_all")
    def test_missing_placeholder(self, mock_get_all):
        mock_get_all.return_value = []
        source = ManualRateSource()
        pricing_dt = datetime(2023, 6, 1)
        res = source.resolve("A", "C1", pricing_dt)
        self.assertEqual(res[0].rate_freshness, "Missing")
        self.assertEqual(res[0].delivered_rate, 0.0)

    @patch("frappe.get_all")
    def test_confidence_score(self, mock_get_all):
        mock_get_all.return_value = [
            DummyRecord(name="MR1", item="A", city="C1", supplier="S1", delivered_rate=100.0, 
                        is_active=1, valid_from="2023-05-15 00:00:00", valid_to=None, rate_type="All-In Delivered", ex_works_rate=0, credit_days=30, lead_time_days=5),
            DummyRecord(name="MR2", item="A", city="C1", supplier="S1", delivered_rate=110.0, 
                        is_active=0, valid_from="2023-01-01 00:00:00", valid_to=None, rate_type="All-In Delivered", ex_works_rate=0, credit_days=30, lead_time_days=5),
            DummyRecord(name="MR3", item="A", city="C1", supplier="S1", delivered_rate=120.0, 
                        is_active=0, valid_from="2022-01-01 00:00:00", valid_to=None, rate_type="All-In Delivered", ex_works_rate=0, credit_days=30, lead_time_days=5)
        ]
        source = ManualRateSource()
        pricing_dt = datetime(2023, 6, 1)
        res = source.resolve("A", "C1", pricing_dt)
        self.assertEqual(res[0].confidence_score, 50.0)

    @patch("frappe.get_all")
    def test_batch_resolve(self, mock_get_all):
        mock_get_all.return_value = [
            DummyRecord(name="MR1", item="A", city="C1", supplier="S1", delivered_rate=100.0, 
                        is_active=1, valid_from="2023-01-01 00:00:00", valid_to=None, rate_type="All-In Delivered", ex_works_rate=0, credit_days=0, lead_time_days=0),
            DummyRecord(name="MR2", item="B", city="C2", supplier="S2", delivered_rate=200.0, 
                        is_active=1, valid_from="2023-01-01 00:00:00", valid_to=None, rate_type="All-In Delivered", ex_works_rate=0, credit_days=0, lead_time_days=0)
        ]
        source = ManualRateSource()
        res = source.batch_resolve([("A", "C1"), ("B", "C2"), ("C", "C3")], datetime(2023, 6, 1))
        self.assertEqual(len(res), 3)
        self.assertEqual(res[("A", "C1")][0].supplier, "S1")
        self.assertEqual(res[("B", "C2")][0].supplier, "S2")
        self.assertEqual(res[("C", "C3")][0].rate_freshness, "Missing")

import unittest
from mpd_customizations.costing.services.cost_calculator import (
    compute_rm_line_amount,
    compute_financing_cost_for_line,
    compute_processing_cost,
    compute_additional_charge_amount,
    compute_total_cost,
    compute_internal_earnings
)

class TestCostCalculator(unittest.TestCase):
    def test_rm_line_amount(self):
        self.assertAlmostEqual(compute_rm_line_amount(2.5, 100), 250.0)

    def test_financing_cost_credit_exceeds_production(self):
        # 30 days prod, 45 days credit
        self.assertEqual(compute_financing_cost_for_line(1000, 30, 45, 12.0), 0.0)

    def test_financing_cost_partial_credit(self):
        # 30 days prod, 15 days credit, net 15 days, 12% pa on 1000 = 1000 * 15/365 * 0.12
        expected = 1000.0 * (15.0 / 365.0) * (12.0 / 100.0)
        self.assertAlmostEqual(compute_financing_cost_for_line(1000, 30, 15, 12.0), expected)

    def test_financing_cost_zero_credit(self):
        expected = 1000.0 * (30.0 / 365.0) * (12.0 / 100.0)
        self.assertAlmostEqual(compute_financing_cost_for_line(1000, 30, 0, 12.0), expected)

    def test_processing_cost(self):
        self.assertAlmostEqual(compute_processing_cost(50.0, 20.0), 10.0)
        self.assertAlmostEqual(compute_processing_cost(1.0, 100.0), 1.0)
        self.assertAlmostEqual(compute_processing_cost(99.0, 10.0), 9.9)

    def test_additional_charge_amount(self):
        self.assertEqual(compute_additional_charge_amount(5.0, "Per kg of Output", 50.0), 5.0)
        self.assertEqual(compute_additional_charge_amount(10.0, "Per kg of Solids", 50.0), 5.0)

    def test_total_cost(self):
        self.assertEqual(compute_total_cost(10, 2, 3, 4, 1), 20.0)

    def test_internal_earnings_positive_spread(self):
        lines = [
            {"item_name": "A", "amount_per_kg": 1000, "production_days": 30, "supplier_credit_days": 0}
        ]
        # Supplier rate 12%, Actual cost of capital 9% -> spread 3%
        res = compute_internal_earnings(lines, 1000.0, 9.0, 12.0)
        expected = 1000.0 * (30.0 / 365.0) * (3.0 / 100.0)
        self.assertAlmostEqual(res["total_spread_per_kg"], expected)

    def test_internal_earnings_zero_spread(self):
        lines = [
            {"item_name": "A", "amount_per_kg": 1000, "production_days": 30, "supplier_credit_days": 0}
        ]
        res = compute_internal_earnings(lines, 1000.0, 12.0, 12.0)
        self.assertEqual(res["total_spread_per_kg"], 0.0)

    def test_internal_earnings_negative_spread_impossible(self):
        lines = [
            {"item_name": "A", "amount_per_kg": 1000, "production_days": 30, "supplier_credit_days": 0}
        ]
        res = compute_internal_earnings(lines, 1000.0, 15.0, 12.0)
        self.assertEqual(res["total_spread_per_kg"], 0.0)

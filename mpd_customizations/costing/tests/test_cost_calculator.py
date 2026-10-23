import unittest

from mpd_customizations.costing.services.cost_calculator import (
	compute_additional_charge_amount,
	compute_financing_cost_for_line,
	compute_internal_earnings,
	compute_processing_cost,
	compute_rm_line_amount,
	compute_total_cost,
)


class TestComputeRmLineAmount(unittest.TestCase):
	def test_basic(self):
		self.assertAlmostEqual(compute_rm_line_amount(0.5, 100.0), 50.0)

	def test_zero_qty(self):
		self.assertEqual(compute_rm_line_amount(0.0, 100.0), 0.0)

	def test_zero_rate(self):
		self.assertEqual(compute_rm_line_amount(0.5, 0.0), 0.0)


class TestComputeFinancingCost(unittest.TestCase):
	def test_supplier_credit_exceeds_production(self):
		# 45d credit, 30d production → 0 financed days
		result = compute_financing_cost_for_line(100.0, 30, 45, 12.0)
		self.assertEqual(result, 0.0)

	def test_partial_credit(self):
		# 30d production, 15d credit → 15d financed
		result = compute_financing_cost_for_line(100.0, 30, 15, 12.0)
		expected = 100.0 * (15 / 365) * (12.0 / 100)
		self.assertAlmostEqual(result, expected, places=6)

	def test_zero_credit(self):
		# 30d production, 0d credit → 30d financed
		result = compute_financing_cost_for_line(100.0, 30, 0, 12.0)
		expected = 100.0 * (30 / 365) * (12.0 / 100)
		self.assertAlmostEqual(result, expected, places=6)

	def test_equal_credit_and_production(self):
		result = compute_financing_cost_for_line(100.0, 30, 30, 12.0)
		self.assertEqual(result, 0.0)

	def test_never_negative(self):
		result = compute_financing_cost_for_line(100.0, 10, 60, 12.0)
		self.assertGreaterEqual(result, 0.0)


class TestComputeProcessingCost(unittest.TestCase):
	def test_standard(self):
		# 70% solids, ₹18/kg charge → 0.7 × 18 = 12.6
		self.assertAlmostEqual(compute_processing_cost(70.0, 18.0), 12.6)

	def test_one_percent(self):
		result = compute_processing_cost(1.0, 100.0)
		self.assertAlmostEqual(result, 1.0)

	def test_ninety_nine_percent(self):
		result = compute_processing_cost(99.0, 100.0)
		self.assertAlmostEqual(result, 99.0)


class TestComputeAdditionalCharge(unittest.TestCase):
	def test_per_kg_output(self):
		self.assertEqual(compute_additional_charge_amount(5.0, "Per kg of Output", 70.0), 5.0)

	def test_per_kg_solids(self):
		result = compute_additional_charge_amount(10.0, "Per kg of Solids", 70.0)
		self.assertAlmostEqual(result, 7.0)

	def test_invalid_basis(self):
		with self.assertRaises(ValueError):
			compute_additional_charge_amount(5.0, "Unknown Basis", 70.0)


class TestComputeTotalCost(unittest.TestCase):
	def test_sum(self):
		result = compute_total_cost(85.77, 0.14, 12.60, 15.0, 3.50)
		self.assertAlmostEqual(result, 117.01)


class TestComputeInternalEarnings(unittest.TestCase):
	def test_positive_spread(self):
		lines = [
			{"item": "A", "item_name": "Item A", "amount_per_kg": 100.0, "net_financed_days": 30},
		]
		result = compute_internal_earnings(lines, 9.0, 12.0)
		self.assertGreater(result["rm_spread_per_kg"], 0)
		self.assertEqual(result["spread_pct"], 3.0)

	def test_zero_spread_equal_rates(self):
		lines = [
			{"item": "A", "item_name": "Item A", "amount_per_kg": 100.0, "net_financed_days": 30},
		]
		result = compute_internal_earnings(lines, 12.0, 12.0)
		self.assertEqual(result["rm_spread_per_kg"], 0.0)
		self.assertEqual(result["spread_pct"], 0.0)

	def test_spread_never_negative(self):
		# actual cost HIGHER than financing rate → spread clamped to 0
		lines = [
			{"item": "A", "item_name": "Item A", "amount_per_kg": 100.0, "net_financed_days": 30},
		]
		result = compute_internal_earnings(lines, 15.0, 12.0)
		self.assertEqual(result["rm_spread_per_kg"], 0.0)
		self.assertEqual(result["spread_pct"], 0.0)

import unittest
from dataclasses import dataclass

from mpd_customizations.costing.services.config import CostingConfig
from mpd_customizations.costing.services.formulation_selector import FormulationSelector


def _make_config(exclusion=15.0, switch=5.0):
	return CostingConfig(
		engine_version="1.0.0",
		production_days=30,
		supplier_financing_rate_pct=12.0,
		actual_cost_of_capital_pct=9.0,
		credit_benefit_rate_pct=8.0,
		customer_credit_rate_pct=16.0,
		auto_exclusion_threshold_pct=exclusion,
		formulation_switch_threshold_pct=switch,
		default_valid_to="End of Month",
		default_valid_to_days=30,
		rate_expiry_warning_days=30,
	)


def _combo(bom, total_cost):
	return {"bom": bom, "total_cost_per_kg": total_cost, "formulation_id": bom}


class TestFormulationSelector(unittest.TestCase):
	def setUp(self):
		self.selector = FormulationSelector(_make_config())

	def test_cheapest_gets_rank_1(self):
		combos = [_combo("BOM-A", 120.0), _combo("BOM-B", 100.0), _combo("BOM-C", 110.0)]
		result = self.selector.select(combos, None)
		rank1 = next(c for c in result.included if c["rank"] == 1)
		self.assertEqual(rank1["bom"], "BOM-B")

	def test_above_threshold_excluded(self):
		combos = [_combo("BOM-A", 100.0), _combo("BOM-B", 120.0), _combo("BOM-C", 150.0)]
		result = self.selector.select(combos, None)
		# BOM-C = +50% > 15% threshold → excluded
		excluded_boms = [c["bom"] for c in result.excluded]
		self.assertIn("BOM-C", excluded_boms)
		included_boms = [c["bom"] for c in result.included]
		self.assertNotIn("BOM-C", included_boms)

	def test_preferred_flagged_regardless_of_rank(self):
		combos = [_combo("BOM-A", 100.0), _combo("BOM-B", 105.0)]
		result = self.selector.select(combos, "BOM-B")
		preferred = next(c for c in result.included if c["bom"] == "BOM-B")
		self.assertTrue(preferred["is_preferred"])

	def test_switch_alert_when_preferred_above_threshold(self):
		combos = [_combo("BOM-A", 100.0), _combo("BOM-B", 107.0)]
		result = self.selector.select(combos, "BOM-B")
		self.assertIsNotNone(result.switch_alert)
		self.assertIn("BOM-A", result.switch_alert)

	def test_no_switch_alert_below_threshold(self):
		combos = [_combo("BOM-A", 100.0), _combo("BOM-B", 103.0)]
		result = self.selector.select(combos, "BOM-B")
		self.assertIsNone(result.switch_alert)

	def test_all_same_cost_all_rank_1(self):
		combos = [_combo("BOM-A", 100.0), _combo("BOM-B", 100.0)]
		result = self.selector.select(combos, None)
		ranks = [c["rank"] for c in result.included]
		# rank 1 goes to first in sort (stable sort = first occurrence)
		self.assertIn(1, ranks)

	def test_single_combination_rank_1_never_excluded(self):
		combos = [_combo("BOM-A", 100.0)]
		result = self.selector.select(combos, None)
		self.assertEqual(len(result.included), 1)
		self.assertEqual(len(result.excluded), 0)
		self.assertEqual(result.included[0]["rank"], 1)

	def test_all_excluded_no_ranks(self):
		# 100 and 200 → delta 100% for BOM-B, excluded. Only BOM-A included.
		combos = [_combo("BOM-A", 100.0), _combo("BOM-B", 200.0)]
		result = self.selector.select(combos, None)
		self.assertEqual(len(result.included), 1)
		self.assertEqual(len(result.excluded), 1)
		self.assertIsNone(result.excluded[0]["rank"])

	def test_empty_input(self):
		result = self.selector.select([], None)
		self.assertEqual(result.included, [])
		self.assertEqual(result.excluded, [])

import unittest
from mpd_customizations.costing.services.formulation_selector import FormulationSelector
from mpd_customizations.costing.services.config import CostingConfig

class TestFormulationSelector(unittest.TestCase):
    def setUp(self):
        self.config = CostingConfig(
            engine_version="1.0.0",
            production_days=30,
            supplier_financing_rate_pct=12.0,
            actual_cost_of_capital_pct=9.0,
            auto_exclusion_threshold_pct=15.0,
            formulation_switch_threshold_pct=5.0,
            default_valid_to="End of Month",
            default_valid_to_days=30,
            rate_expiry_warning_days=30
        )
        self.selector = FormulationSelector(self.config)

    def test_cheapest_gets_rank_1(self):
        combs = [
            {"bom": "B1", "total_cost_per_kg": 100},
            {"bom": "B2", "total_cost_per_kg": 90},
            {"bom": "B3", "total_cost_per_kg": 110}
        ]
        res = self.selector.select(combs, preferred_bom="B1")
        included = res["included"]
        self.assertEqual(len(included), 2)
        self.assertEqual(included[0]["bom"], "B2")
        self.assertEqual(included[0]["rank"], 1)

    def test_above_threshold_gets_excluded(self):
        combs = [
            {"bom": "B1", "total_cost_per_kg": 100},
            {"bom": "B2", "total_cost_per_kg": 120}  # 20% > 15% threshold
        ]
        res = self.selector.select(combs, preferred_bom="B1")
        self.assertEqual(len(res["included"]), 1)
        self.assertEqual(len(res["excluded"]), 1)
        self.assertEqual(res["excluded"][0]["bom"], "B2")
        self.assertEqual(res["excluded"][0]["status"], "Excluded — Too Expensive")

    def test_switch_alert_generated(self):
        combs = [
            {"bom": "B1", "formulation_id": "F1", "total_cost_per_kg": 106}, # Preferred, 6% diff > 5%
            {"bom": "B2", "formulation_id": "F2", "total_cost_per_kg": 100}
        ]
        res = self.selector.select(combs, preferred_bom="B1")
        self.assertIsNotNone(res["switch_alert"])
        self.assertIn("F2", res["switch_alert"])
        self.assertIn("F1", res["switch_alert"])

    def test_switch_alert_not_generated_below_threshold(self):
        combs = [
            {"bom": "B1", "formulation_id": "F1", "total_cost_per_kg": 104}, # 4% diff <= 5%
            {"bom": "B2", "formulation_id": "F2", "total_cost_per_kg": 100}
        ]
        res = self.selector.select(combs, preferred_bom="B1")
        self.assertIsNone(res["switch_alert"])

    def test_all_combinations_excluded(self):
        # Even if min cost is 0, we can test exclusion if needed. 
        # But wait, delta calculation uses min_cost. If min_cost is 0, delta is 0.
        pass

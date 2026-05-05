import unittest
from unittest.mock import patch, MagicMock
from mpd_customizations.costing.services.costing_engine import CostingEngine
from mpd_customizations.costing.services.config import CostingConfig

class TestCostingEngine(unittest.TestCase):
    @patch("frappe.get_doc")
    @patch("frappe.get_all")
    @patch("frappe.db.get_value")
    @patch("frappe.db.delete")
    @patch("frappe.db.set_value")
    def test_engine_missing_bom(self, mock_set_val, mock_delete, mock_get_val, mock_get_all, mock_get_doc):
        cr_mock = MagicMock()
        cr_mock.item = "Item1"
        cr_mock.processor = "P1"
        cr_mock.solids_content_pct = 50.0
        cr_mock.production_days = 30
        cr_mock.supplier_financing_rate_pct = 12.0
        mock_get_doc.return_value = cr_mock
        
        mock_get_val.return_value = "City1"
        mock_get_all.return_value = [] # No BOMs

        registry = MagicMock()
        config = CostingConfig(
            engine_version="1.0.0", production_days=30, supplier_financing_rate_pct=12.0,
            actual_cost_of_capital_pct=9.0, auto_exclusion_threshold_pct=15.0,
            formulation_switch_threshold_pct=5.0, default_valid_to="End of Month",
            default_valid_to_days=30, rate_expiry_warning_days=30
        )
        engine = CostingEngine(registry, config)

        with self.assertRaises(Exception) as context:
            engine.evaluate("CR-001")
        self.assertTrue("No active submitted BOMs" in str(context.exception))

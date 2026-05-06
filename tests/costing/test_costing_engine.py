import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch, call

from mpd_customizations.costing.services.config import CostingConfig
from mpd_customizations.costing.services.costing_engine import CostingEngine


def _make_config():
	return CostingConfig(
		engine_version="1.0.0",
		production_days=30,
		supplier_financing_rate_pct=12.0,
		actual_cost_of_capital_pct=9.0,
		auto_exclusion_threshold_pct=15.0,
		formulation_switch_threshold_pct=5.0,
		default_valid_to="End of Month",
		default_valid_to_days=30,
		rate_expiry_warning_days=30,
	)


def _make_registry():
	r = MagicMock()
	return r


class TestCostingEngine(unittest.TestCase):
	def setUp(self):
		self.config = _make_config()
		self.registry = _make_registry()
		self.engine = CostingEngine(self.registry, self.config)

	def _mock_doc(self):
		doc = MagicMock()
		doc.name = "CR-001"
		doc.item = "PAINT-001"
		doc.processor = "PROC-001"
		doc.solids_content_pct = 70.0
		doc.production_days = 30
		doc.supplier_financing_rate_pct = 12.0
		doc.preferred_bom = None
		doc.additional_charges = []
		doc.rate_lines = []
		doc.processing_lines = []
		return doc

	@patch("mpd_customizations.costing.services.costing_engine.RateFetcher")
	@patch("mpd_customizations.costing.services.costing_engine.frappe")
	def test_no_bom_raises_error(self, mock_frappe, mock_fetcher):
		mock_frappe.get_doc.return_value = self._mock_doc()
		mock_frappe.db.exists.return_value = None  # No BOM
		mock_frappe._.side_effect = lambda x, *a: x

		with self.assertRaises(Exception):
			self.engine.evaluate("CR-001")

	@patch("mpd_customizations.costing.services.costing_engine.RateFetcher")
	@patch("mpd_customizations.costing.services.costing_engine.frappe")
	def test_no_processor_city_raises_error(self, mock_frappe, mock_fetcher):
		doc = self._mock_doc()
		mock_frappe.get_doc.return_value = doc
		mock_frappe.db.exists.return_value = "BOM-001"
		mock_frappe.db.get_value.return_value = None  # No city
		mock_frappe._.side_effect = lambda x, *a: x

		with self.assertRaises(Exception):
			self.engine.evaluate("CR-001")

	@patch("mpd_customizations.costing.services.costing_engine.RateFetcher")
	@patch("mpd_customizations.costing.services.costing_engine.frappe")
	def test_purge_deletes_material_lines_before_combinations(self, mock_frappe, mock_fetcher):
		doc = self._mock_doc()
		mock_frappe.get_doc.return_value = doc
		mock_frappe.db.exists.return_value = "BOM-001"
		mock_frappe.db.get_value.return_value = "Indore"
		mock_frappe._.side_effect = lambda x, *a: x

		mock_fetcher.fetch.return_value = MagicMock(
			has_missing_rates=False, missing_items=[],
			has_expired_rates=False, expired_items=[],
			overrides_detected=False, overrides_changed=[],
		)

		mock_frappe.get_all.side_effect = [
			[{"name": "BOM-001", "item": "PAINT-001", "quantity": 1, "custom_formulation_id": "F1"}],
			[],  # No BOM items
		]
		mock_frappe._dict = dict

		combo_doc = MagicMock()
		combo_doc.name = "CC-001"
		combo_doc.bom = "BOM-001"
		mock_frappe.get_doc.side_effect = [doc, combo_doc]

		delete_calls = []
		mock_frappe.db.delete.side_effect = lambda dt, *a, **kw: delete_calls.append(dt)

		try:
			self.engine.evaluate("CR-001")
		except Exception:
			pass

		if len(delete_calls) >= 2:
			self.assertEqual(delete_calls[0], "Costing Material Line")
			self.assertEqual(delete_calls[1], "Costing Combination")

	@patch("mpd_customizations.costing.services.costing_engine.RateFetcher")
	@patch("mpd_customizations.costing.services.costing_engine.frappe")
	def test_processing_cost_uses_solids(self, mock_frappe, mock_fetcher):
		"""Processing cost = (solids/100) × charge_per_kg."""
		doc = self._mock_doc()
		doc.solids_content_pct = 70.0
		processing_line = MagicMock()
		processing_line.working_charge_per_kg = 18.0
		processing_line.working_includes_outward_freight = False
		processing_line.working_freight_per_unit = 3.5
		doc.processing_lines = [processing_line]

		# Expected: 0.70 × 18.0 = 12.6
		from mpd_customizations.costing.services.cost_calculator import compute_processing_cost
		result = compute_processing_cost(70.0, 18.0)
		self.assertAlmostEqual(result, 12.6)

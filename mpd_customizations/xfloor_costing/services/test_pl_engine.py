import unittest

from mpd_customizations.xfloor_costing.services import pl_engine


class TestPLEngine(unittest.TestCase):
	def test_calc_project_summary(self):
		result = pl_engine.calc_project(
			{
				"sqft": 1000,
				"rate_per_sqft": 70,
				"top_coat_option": "1mm",
				"screed_option": "1mm",
				"coving_kits": 2,
				"hibuild_kits": 1,
				"applicator_rate": 8,
			},
			settings={**pl_engine.DEFAULT_RATES, **pl_engine.DEFAULT_COVERAGE},
		)
		self.assertIn("summary", result)
		self.assertGreater(result["summary"]["contract_value"], 0)
		self.assertEqual(len(result["budget_rows"]), 6)

	def test_actual_totals(self):
		totals = pl_engine.calc_actual_totals(
			[
				{"component": "Top coat", "kits": 5, "rate_per_kit": 4000},
				{"component": "Screed", "kits": 2, "rate_per_kit": 3000},
			]
		)
		self.assertEqual(totals["kits"], 7)
		self.assertEqual(totals["cost"], 26000)


if __name__ == "__main__":
	unittest.main()

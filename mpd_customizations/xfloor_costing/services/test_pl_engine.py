import math
import unittest

from mpd_customizations.xfloor_costing.services import pl_engine


SETTINGS = {**pl_engine.DEFAULT_RATES, **pl_engine.DEFAULT_COVERAGE}


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
			settings=SETTINGS,
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

	def test_zero_topcoat_and_screed(self):
		result = pl_engine.calc_project(
			{
				"sqft": 1000,
				"rate_per_sqft": 70,
				"top_coat_option": "0",
				"screed_option": "0",
				"coving_kits": 0,
				"hibuild_kits": 0,
				"applicator_rate": 0,
			},
			settings=SETTINGS,
		)
		by_component = {row["component"]: row for row in result["budget_rows"]}
		self.assertEqual(by_component["Top coat"]["kits"], 0)
		self.assertEqual(by_component["Top coat"]["cost"], 0)
		self.assertEqual(by_component["Screed"]["kits"], 0)
		self.assertEqual(by_component["Screed"]["cost"], 0)

	def test_multi_part_aggregation(self):
		# Part A: 10000 sqft @70, 1mm TC, 2mm screed, coving 2, applicator 8
		# Part B: 2000 sqft @90, 1mm TC only, hibuild 1, applicator 12
		result = pl_engine.calc_project(
			{
				"parts": [
					{
						"part_name": "Warehouse",
						"sqft": 10000,
						"rate_per_sqft": 70,
						"top_coat_option": "1mm",
						"screed_option": "2mm",
						"coving_kits": 2,
						"hibuild_kits": 0,
						"applicator_rate": 8,
					},
					{
						"part_name": "Office",
						"sqft": 2000,
						"rate_per_sqft": 90,
						"top_coat_option": "1mm",
						"screed_option": "0",
						"coving_kits": 0,
						"hibuild_kits": 1,
						"applicator_rate": 12,
					},
				],
			},
			settings=SETTINGS,
		)

		self.assertEqual(len(result["part_budgets"]), 2)
		self.assertEqual(result["summary"]["contract_value"], 10000 * 70 + 2000 * 90)

		tc_cov = SETTINGS["top_coat_1mm_coverage"]
		sc_cov = SETTINGS["screed_2mm_coverage"]
		expected_tc = math.ceil(10000 / tc_cov) + math.ceil(2000 / tc_cov)
		expected_sc = math.ceil(10000 / sc_cov) + 0

		by_component = {row["component"]: row for row in result["budget_rows"]}
		self.assertEqual(by_component["Top coat"]["kits"], expected_tc)
		self.assertEqual(by_component["Screed"]["kits"], expected_sc)
		self.assertEqual(by_component["Screed"]["option"], "mixed")
		self.assertEqual(by_component["Coving"]["kits"], 2)
		self.assertEqual(by_component["Hi-build"]["kits"], 1)

		expected_app = 10000 * 8 + 2000 * 12
		self.assertEqual(by_component["Applicator"]["cost"], expected_app)

		part_a = result["part_budgets"][0]
		part_b = result["part_budgets"][1]
		self.assertEqual(part_a["part_name"], "Warehouse")
		self.assertEqual(part_a["rate_per_sqft"], 70)
		self.assertEqual(
			{r["component"]: r["kits"] for r in part_a["budget_rows"]}["Screed"],
			math.ceil(10000 / sc_cov),
		)
		self.assertEqual(
			{r["component"]: r["kits"] for r in part_b["budget_rows"]}["Screed"],
			0,
		)
		self.assertEqual(
			{r["component"]: r["kits"] for r in part_b["budget_rows"]}["Hi-build"],
			1,
		)

	def test_legacy_flat_matches_single_part(self):
		flat = pl_engine.calc_project(
			{
				"sqft": 1000,
				"rate_per_sqft": 70,
				"top_coat_option": "1mm",
				"screed_option": "1mm",
				"coving_kits": 2,
				"hibuild_kits": 1,
				"applicator_rate": 8,
			},
			settings=SETTINGS,
		)
		parts = pl_engine.calc_project(
			{
				"parts": [
					{
						"part_name": "Main",
						"sqft": 1000,
						"rate_per_sqft": 70,
						"top_coat_option": "1mm",
						"screed_option": "1mm",
						"coving_kits": 2,
						"hibuild_kits": 1,
						"applicator_rate": 8,
					}
				],
			},
			settings=SETTINGS,
		)
		self.assertAlmostEqual(flat["summary"]["total_cost"], parts["summary"]["total_cost"])
		self.assertAlmostEqual(flat["summary"]["contract_value"], parts["summary"]["contract_value"])

	def test_flat_fields_to_main_part(self):
		part = pl_engine.flat_fields_to_main_part(
			{
				"sqft": 5000,
				"rate_per_sqft": 65,
				"top_coat_option": "2mm",
				"screed_option": "0",
				"coving_kits": 3,
				"hibuild_kits": 2,
				"applicator_rate": 9.5,
			}
		)
		self.assertEqual(part["part_name"], "Main")
		self.assertEqual(part["sqft"], 5000)
		self.assertEqual(part["rate_per_sqft"], 65)
		self.assertEqual(part["coving_kits"], 3)
		self.assertEqual(part["hibuild_kits"], 2)
		self.assertEqual(part["top_coat_option"], "2mm")
		self.assertEqual(part["screed_option"], "0")
		self.assertEqual(part["applicator_rate"], 9.5)

		flat = pl_engine.calc_project(
			{
				"sqft": 5000,
				"rate_per_sqft": 65,
				"top_coat_option": "2mm",
				"screed_option": "0",
				"coving_kits": 3,
				"hibuild_kits": 2,
				"applicator_rate": 9.5,
			},
			settings=SETTINGS,
		)
		migrated = pl_engine.calc_project({"parts": [part]}, settings=SETTINGS)
		self.assertAlmostEqual(flat["summary"]["total_cost"], migrated["summary"]["total_cost"])
		self.assertAlmostEqual(flat["summary"]["profit_loss"], migrated["summary"]["profit_loss"])


if __name__ == "__main__":
	unittest.main()

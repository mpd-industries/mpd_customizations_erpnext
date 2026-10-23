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
		self.assertEqual(len(result["budget_rows"]), 7)

	def test_actual_totals(self):
		totals = pl_engine.calc_actual_totals(
			[
				{"component": "Epoxy Top coat", "kits": 5, "rate_per_kit": 4000},
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
				"pu_top_coat_option": "0",
				"screed_option": "0",
				"coving_kits": 0,
				"hibuild_kits": 0,
				"applicator_rate": 0,
			},
			settings=SETTINGS,
		)
		by_component = {row["component"]: row for row in result["budget_rows"]}
		self.assertEqual(by_component["Epoxy Top coat"]["kits"], 0)
		self.assertEqual(by_component["Epoxy Top coat"]["cost"], 0)
		self.assertEqual(by_component["PU Top coat"]["kits"], 0)
		self.assertEqual(by_component["Screed"]["kits"], 0)
		self.assertEqual(by_component["Screed"]["cost"], 0)

	def test_pu_top_coat_and_screed_7mm(self):
		result = pl_engine.calc_project(
			{
				"sqft": 1000,
				"rate_per_sqft": 70,
				"top_coat_option": "0",
				"pu_top_coat_option": "1mm",
				"screed_option": "7mm",
				"coving_kits": 0,
				"hibuild_kits": 0,
				"applicator_rate": 0,
			},
			settings=SETTINGS,
		)
		by_component = {row["component"]: row for row in result["budget_rows"]}
		pu_cov = SETTINGS["pu_top_coat_1mm_coverage"]
		sc_cov = SETTINGS["screed_7mm_coverage"]
		self.assertEqual(by_component["Epoxy Top coat"]["kits"], 0)
		self.assertEqual(by_component["PU Top coat"]["kits"], math.ceil(1000 / pu_cov))
		self.assertEqual(by_component["Screed"]["kits"], math.ceil(1000 / sc_cov))
		self.assertEqual(by_component["Screed"]["option"], "7mm")
		self.assertEqual(
			by_component["PU Top coat"]["cost"],
			by_component["PU Top coat"]["kits"] * SETTINGS["pu_top_coat_rate"],
		)

	def test_multi_part_aggregation(self):
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
		self.assertEqual(by_component["Epoxy Top coat"]["kits"], expected_tc)
		self.assertEqual(by_component["Screed"]["kits"], expected_sc)
		self.assertEqual(by_component["Screed"]["option"], "mixed")
		self.assertEqual(by_component["Coving"]["kits"], 2)
		self.assertEqual(by_component["Hi-build"]["kits"], 1)

		expected_app = 10000 * 8 + 2000 * 12
		self.assertEqual(by_component["Applicator"]["cost"], expected_app)

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
				"top_coat_option": "0",
				"pu_top_coat_option": "1mm",
				"screed_option": "0",
				"coving_kits": 3,
				"hibuild_kits": 2,
				"applicator_rate": 9.5,
			}
		)
		self.assertEqual(part["part_name"], "Main")
		self.assertEqual(part["pu_top_coat_option"], "1mm")
		self.assertEqual(part["top_coat_option"], "0")

		flat = pl_engine.calc_project(
			{
				"sqft": 5000,
				"rate_per_sqft": 65,
				"top_coat_option": "0",
				"pu_top_coat_option": "1mm",
				"screed_option": "0",
				"coving_kits": 3,
				"hibuild_kits": 2,
				"applicator_rate": 9.5,
			},
			settings=SETTINGS,
		)
		migrated = pl_engine.calc_project({"parts": [part]}, settings=SETTINGS)
		self.assertAlmostEqual(flat["summary"]["total_cost"], migrated["summary"]["total_cost"])

	def test_kit_gross_margin_aggregation(self):
		settings = {
			**SETTINGS,
			"top_coat_gm": 500,
			"pu_top_coat_gm": 400,
			"screed_gm": 300,
			"primer_gm": 100,
			"coving_gm": 200,
			"hibuild_gm": 150,
		}
		result = pl_engine.calc_project(
			{
				"parts": [
					{
						"part_name": "A",
						"sqft": 1000,
						"rate_per_sqft": 70,
						"top_coat_option": "1mm",
						"screed_option": "1mm",
						"coving_kits": 2,
						"hibuild_kits": 0,
						"applicator_rate": 8,
					},
					{
						"part_name": "B",
						"sqft": 500,
						"rate_per_sqft": 80,
						"top_coat_option": "1mm",
						"screed_option": "0",
						"coving_kits": 0,
						"hibuild_kits": 1,
						"applicator_rate": 10,
					},
				],
			},
			settings=settings,
		)
		ms = result["margin_summary"]
		tc_cov = settings["top_coat_1mm_coverage"]
		sc_cov = settings["screed_1mm_coverage"]
		pr_cov = settings["primer_coverage"]
		tc_kits = math.ceil(1000 / tc_cov) + math.ceil(500 / tc_cov)
		sc_kits = math.ceil(1000 / sc_cov) + 0
		pr_kits = math.ceil(1000 / pr_cov) + math.ceil(500 / pr_cov)

		by_component = {r["component"]: r for r in ms["by_component"]}
		self.assertEqual(by_component["Epoxy Top coat"]["gm_amount"], tc_kits * 500)
		self.assertEqual(by_component["Screed"]["gm_amount"], sc_kits * 300)
		self.assertNotIn("Applicator", by_component)

		expected_total = (
			tc_kits * 500 + sc_kits * 300 + pr_kits * 100 + 2 * 200 + 1 * 150
		)
		self.assertEqual(ms["total_kit_gm"], expected_total)
		self.assertEqual(ms["adjusted_gross_margin"], ms["profit_loss"] + ms["total_kit_gm"])

		budget_by = {r["component"]: r for r in result["budget_rows"]}
		self.assertEqual(budget_by["Epoxy Top coat"]["gm_per_kit"], 500)

	def test_build_price_list(self):
		pl = pl_engine.build_price_list(SETTINGS)
		epoxy_1mm = next(r for r in pl["unit_rates"]["epoxy"] if r["option"] == "1mm")
		expected = SETTINGS["top_coat_rate"] / SETTINGS["top_coat_1mm_coverage"]
		self.assertAlmostEqual(epoxy_1mm["per_sqft"], expected)
		self.assertAlmostEqual(epoxy_1mm["per_sqm"], expected * pl_engine.SQFT_PER_SQM)

		self.assertEqual(pl["applicator_rate"], SETTINGS["default_applicator_rate"])
		self.assertTrue(pl["matrix"])
		self.assertEqual(len(pl["matrix"]), (6 + 4) * 7)
		row0 = next(r for r in pl["matrix"] if r["label"] == "Epoxy TC 0 mm Screed 1 mm")
		self.assertEqual(row0["top_coat"], 0.0)
		self.assertEqual(row0["top_coat_display"], "")

		row = next(r for r in pl["matrix"] if r["label"] == "Epoxy TC 1 mm Screed 1 mm")
		primer = pl_engine.round_price_list_rate(SETTINGS["primer_rate"] / SETTINGS["primer_coverage"])
		screed = pl_engine.round_price_list_rate(SETTINGS["screed_rate"] / SETTINGS["screed_1mm_coverage"])
		top = pl_engine.round_price_list_rate(SETTINGS["top_coat_rate"] / SETTINGS["top_coat_1mm_coverage"])
		app = pl_engine.round_price_list_rate(SETTINGS["default_applicator_rate"])
		self.assertEqual(row["primer"], primer)
		self.assertEqual(row["screed"], screed)
		self.assertEqual(row["top_coat"], top)
		self.assertEqual(row["application"], app)
		self.assertEqual(row["total"], primer + screed + top + app)
		self.assertIn("primer_display", row)

		kit_only = {r["component"]: r for r in pl["kit_only"]}
		self.assertEqual(kit_only["Coving"]["rate_per_kit"], SETTINGS["coving_rate"])
		self.assertEqual(kit_only["Hi-build"]["rate_per_kit"], SETTINGS["hibuild_rate"])
		screed_opts = {r["option"] for r in pl["unit_rates"]["screed"]}
		self.assertIn("7mm", screed_opts)

	def test_round_price_list_rate(self):
		self.assertEqual(pl_engine.round_price_list_rate(1.20), 1.0)
		self.assertEqual(pl_engine.round_price_list_rate(1.25), 1.5)
		self.assertEqual(pl_engine.round_price_list_rate(1.37), 1.5)
		self.assertEqual(pl_engine.round_price_list_rate(1.74), 1.5)
		self.assertEqual(pl_engine.round_price_list_rate(1.75), 2.0)
		self.assertEqual(pl_engine.format_price_list_rate(1.0), "1.00")
		self.assertEqual(pl_engine.format_price_list_rate(1.5), "1.50")
		self.assertEqual(pl_engine.format_price_list_rate(0, blank_zero=True), "")
		self.assertEqual(pl_engine.format_price_list_rate(10), "10.00")

	def test_coving_kits_from_feet(self):
		self.assertEqual(pl_engine._coving_kits_from_feet(0, 150), 0)
		self.assertEqual(pl_engine._coving_kits_from_feet(150, 150), 1)
		self.assertEqual(pl_engine._coving_kits_from_feet(151, 150), 2)
		self.assertEqual(pl_engine._coving_kits_from_feet(300, 150), 2)
		self.assertEqual(pl_engine._coving_kits_from_feet(301, 150), 3)

	def test_project_coving_from_running_feet(self):
		result = pl_engine.calc_project(
			{
				"coving_running_feet": 151,
				"parts": [
					{
						"part_name": "A",
						"sqft": 1000,
						"rate_per_sqft": 70,
						"top_coat_option": "1mm",
						"pu_top_coat_option": "0",
						"screed_option": "1mm",
						"coving_kits": 99,
						"hibuild_kits": 0,
						"applicator_rate": 0,
					}
				],
			},
			settings=SETTINGS,
		)
		by_comp = {r["component"]: r for r in result["budget_rows"]}
		self.assertEqual(by_comp["Coving"]["kits"], 2)
		self.assertEqual(by_comp["Coving"]["coverage"], 150)
		self.assertAlmostEqual(by_comp["Coving"]["cost"], 2 * SETTINGS["coving_rate"])
		self.assertEqual(result["coving_kits"], 2)
		# Parts must not also charge coving
		part_coving = next(
			r for r in result["part_budgets"][0]["budget_rows"] if r["component"] == "Coving"
		)
		self.assertEqual(part_coving["kits"], 0)
		self.assertEqual(part_coving["cost"], 0)

	def test_legacy_part_coving_without_running_feet(self):
		result = pl_engine.calc_project(
			{
				"parts": [
					{
						"part_name": "A",
						"sqft": 500,
						"rate_per_sqft": 50,
						"top_coat_option": "1mm",
						"screed_option": "1mm",
						"coving_kits": 3,
						"hibuild_kits": 0,
						"applicator_rate": 0,
					}
				],
			},
			settings=SETTINGS,
		)
		by_comp = {r["component"]: r for r in result["budget_rows"]}
		self.assertEqual(by_comp["Coving"]["kits"], 3)

	def test_strip_gm_from_result(self):
		result = pl_engine.calc_project(
			{
				"sqft": 1000,
				"rate_per_sqft": 70,
				"top_coat_option": "1mm",
				"screed_option": "1mm",
				"coving_kits": 1,
				"hibuild_kits": 0,
				"applicator_rate": 0,
			},
			settings={**SETTINGS, "top_coat_gm": 400},
		)
		stripped = pl_engine.strip_gm_from_result(result)
		self.assertNotIn("margin_summary", stripped)
		self.assertIn("cost_profile", stripped)
		self.assertNotIn("gm_per_kit", stripped["budget_rows"][0])


if __name__ == "__main__":
	unittest.main()

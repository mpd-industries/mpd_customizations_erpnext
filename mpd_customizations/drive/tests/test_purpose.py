import unittest

from mpd_customizations.drive.ai.purpose import (
	accept_model_purpose,
	format_outline,
	learned_purpose,
	purpose_request,
)


class TestLearnedPurpose(unittest.TestCase):
	def test_a_written_meaning_is_kept(self):
		text = learned_purpose(
			[{"document_type": "Drawing", "summary": "A boiler section."}],
			existing="All boiler house drawings, including vendor markups.",
			keep=True,
		)
		self.assertEqual(text, "All boiler house drawings, including vendor markups.")

	def test_meaning_comes_from_the_files_and_the_child_folders(self):
		text = learned_purpose(
			[
				{
					"document_type": "Drawing",
					"summary": "Structural section of the boiler house, drawing 301.",
					"title": "Sections",
				},
				{
					"document_type": "Drawing",
					"summary": "Ground floor plan of the boiler house.",
					"title": "Ground floor",
				},
			],
			children=[{"title": "Vendor markups", "purpose": "Marked-up copies from the contractor."}],
		)
		self.assertIn("Holds Drawing.", text)
		self.assertIn("Structural section of the boiler house, drawing 301.", text)
		self.assertIn("Ground floor plan of the boiler house.", text)
		self.assertIn("Vendor markups (Marked-up copies from the contractor)", text)

	def test_titles_stand_in_when_the_files_have_no_summary(self):
		text = learned_purpose([{"title": "Tax Invoice - Reactor Supply"}, {"title": "GST Challan"}])
		self.assertEqual(text, "Files such as Tax Invoice - Reactor Supply, GST Challan.")


class TestModelPurpose(unittest.TestCase):
	def test_the_request_names_the_folder_and_the_files_inside_it(self):
		payload = purpose_request(
			"Boiler House",
			[{"title": "Sections", "document_type": "Drawing", "summary": "A boiler section."}],
			[{"title": "Vendor markups", "purpose": "Marked-up copies."}],
			existing="Old note",
		)
		self.assertEqual(payload["folder"], "Boiler House")
		self.assertEqual(payload["files"][0]["summary"], "A boiler section.")
		self.assertEqual(payload["folders_inside"][0]["title"], "Vendor markups")
		self.assertEqual(payload["current_meaning"], "Old note")

	def test_a_model_purpose_is_one_cleaned_sentence(self):
		text = accept_model_purpose({"purpose": "  Drawings of the boiler house.  "})
		self.assertEqual(text, "Drawings of the boiler house.")
		self.assertEqual(accept_model_purpose({"purpose": ""}), "")
		self.assertEqual(accept_model_purpose("nope"), "")


class TestOutline(unittest.TestCase):
	def test_the_outline_includes_each_folder_meaning(self):
		text = format_outline(
			[
				{
					"title": "Blueprints",
					"purpose": "Plant drawings and layouts.",
					"children": [
						{"title": "Boiler House", "purpose": "Drawings of the boiler house."},
						{"title": "Plant Building 1", "purpose": ""},
					],
				}
			]
		)
		self.assertIn("Blueprints — Plant drawings and layouts: Boiler House, Plant Building 1", text)
		self.assertIn("  Boiler House — Drawings of the boiler house.", text)
		self.assertNotIn("Plant Building 1 —", text)

	def test_a_folder_with_no_meaning_keeps_its_name(self):
		self.assertEqual(format_outline([{"title": "Invoices", "children": []}]), "Invoices")
		self.assertEqual(format_outline([]), "(none yet)")

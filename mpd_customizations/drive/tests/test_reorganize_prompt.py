import json
import unittest

from mpd_customizations.drive.ai.reorganize import build_reorganize_prompt, select_items_to_apply


FIELDS = {
	"title": "Licence.pdf",
	"original_filename": "scan.pdf",
	"ai_document_type": "Licence",
	"ai_subject": "Statutory Documents",
	"ai_document_date": "2026-01-02",
	"ai_tags": "factory",
	"ai_summary": "A factory licence.",
	"ai_context": {"parties": "MPD"},
}


class TestReorganizePrompt(unittest.TestCase):
	def test_full_json_includes_every_ai_field_and_a_blank_instruction_is_omitted(self):
		prompt = build_reorganize_prompt(FIELDS, "Statutory Documents", "", "Full JSON")
		payload = json.loads(prompt.split("File:\n", 1)[1])
		for key in FIELDS:
			self.assertIn(key, payload)
		self.assertNotIn("User instruction", prompt)
		self.assertNotIn("only the file name", prompt)

	def test_name_only_sends_the_file_name_and_title(self):
		prompt = build_reorganize_prompt(FIELDS, "(none yet)", "", "Name only")
		payload = json.loads(prompt.split("File:\n", 1)[1])
		self.assertEqual(set(payload), {"original_filename", "title"})
		self.assertIn("only the file name", prompt)

	def test_instruction_is_included_when_present(self):
		prompt = build_reorganize_prompt(FIELDS, "Invoices", "Group GST under Challans", "Full JSON")
		self.assertIn("Group GST under Challans", prompt)
		self.assertIn("User instruction", prompt)

	def test_followup_includes_the_previous_proposal_and_asks_for_a_revision(self):
		prompt = build_reorganize_prompt(
			FIELDS,
			"Invoices",
			"File by subject",
			"Full JSON",
			followups=["Put GST files under Challans"],
			previous_plan={"proposed_path": "Documents/Invoices", "proposed_title": "GST"},
		)
		self.assertIn("Previous proposal", prompt)
		self.assertIn("Documents/Invoices", prompt)
		self.assertIn("Put GST files under Challans", prompt)
		self.assertIn("Revise the previous proposal", prompt)


class TestApplySelection(unittest.TestCase):
	def test_only_selected_items_apply_and_a_moved_file_is_skipped(self):
		items = [
			{"name": "i1", "file": "a", "current_folder": "docs"},
			{"name": "i2", "file": "b", "current_folder": "docs"},
			{"name": "i3", "file": "c", "current_folder": "docs"},
		]
		result = select_items_to_apply(items, ["i1", "i3"], {"a": "docs", "b": "docs", "c": "other"})
		self.assertEqual(result["apply"], ["i1"])
		self.assertEqual(result["skip"], ["i3"])

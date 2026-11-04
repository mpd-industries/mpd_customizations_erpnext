import unittest

from mpd_customizations.drive.mcp_tools import DRIVE_TOOL_NAMES, filter_documents

ROWS = [
	{
		"name": "FILE-1",
		"title": "Tax Invoice",
		"folder": "invoices",
		"ai_document_type": "Invoice",
		"ai_subject": "Invoices",
		"ai_document_date": "2026-05-02",
		"ai_summary": "Invoice from Reactor Supply",
		"ai_tags": "gst",
		"ai_suggested_path": "Documents/Invoices/FY 2026-27",
		"original_filename": "scan.pdf",
	},
	{
		"name": "FILE-2",
		"title": "Secret",
		"folder": "hidden",
		"ai_document_type": "Invoice",
		"ai_subject": "Invoices",
		"ai_summary": "Should stay hidden",
		"ai_tags": "",
		"ai_suggested_path": "Documents/Invoices/FY 2026-27",
		"ai_document_date": "2026-05-02",
		"original_filename": "secret.pdf",
	},
]


class TestSchemas(unittest.TestCase):
	def test_drive_tools_are_registered(self):
		self.assertTrue(
			{
				"drive_search",
				"drive_get_document",
				"drive_list_folder",
				"drive_list_review",
				"drive_accept_filing",
				"drive_folder_tree",
			}
			<= DRIVE_TOOL_NAMES
		)


class TestFilter(unittest.TestCase):
	def test_hidden_folder_is_excluded(self):
		found = filter_documents(ROWS, ["invoices"], query="invoice")
		self.assertEqual([row["name"] for row in found], ["FILE-1"])

	def test_year_and_type_filters(self):
		found = filter_documents(ROWS, ["invoices", "hidden"], document_type="Invoice", year="FY 2026-27")
		self.assertEqual({row["name"] for row in found}, {"FILE-1", "FILE-2"})
		found = filter_documents(ROWS, ["invoices"], year="FY 2024-25")
		self.assertEqual(found, [])

	def test_filename_matches_original_name(self):
		found = filter_documents(ROWS, ["invoices"], filename="scan.pdf")
		self.assertEqual([row["name"] for row in found], ["FILE-1"])
		found = filter_documents(ROWS, ["invoices"], filename="secret.pdf")
		self.assertEqual(found, [])

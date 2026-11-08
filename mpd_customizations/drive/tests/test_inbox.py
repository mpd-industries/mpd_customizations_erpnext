import unittest
from datetime import date

from mpd_customizations.drive.ai.filing import (
	APR_HANDLER,
	decide_inbox,
	match_existing_subject,
	reorganize_candidates,
	resolve_subfolder,
	s3_file_url,
	select_route,
	year_label,
)


class TestYearLabels(unittest.TestCase):
	def test_financial_year_from_april(self):
		self.assertEqual(year_label(date(2026, 5, 1), "Financial Year"), "FY 2026-27")

	def test_financial_year_before_april(self):
		self.assertEqual(year_label(date(2026, 3, 31), "Financial Year"), "FY 2025-26")

	def test_calendar_year(self):
		self.assertEqual(year_label(date(2026, 3, 31), "Calendar"), "2026")


class TestFilingDecision(unittest.TestCase):
	def test_reuses_existing_subject_spelling(self):
		self.assertEqual(match_existing_subject("invoices", ["Invoices", "HR"]), "Invoices")

	def test_high_confidence_files_into_subject_and_year(self):
		decision = decide_inbox(
			{
				"subject": "invoices",
				"document_date": "2026-05-02",
				"title": "Tax Invoice - Reactor Supply",
				"confidence": 0.91,
				"use_year": True,
			},
			["Invoices"],
			threshold=0.75,
			year_style="Financial Year",
			today=date(2026, 10, 29),
		)
		self.assertTrue(decision["auto_file"])
		self.assertEqual(decision["ai_status"], "Filed")
		self.assertEqual(decision["subject"], "Invoices")
		self.assertEqual(decision["segments"], ["Invoices", "FY 2026-27"])
		self.assertEqual(decision["title"], "Tax Invoice - Reactor Supply")

	def test_low_confidence_stays_in_review(self):
		decision = decide_inbox(
			{"subject": "HR", "confidence": 0.4},
			[],
			threshold=0.75,
			year_style="Financial Year",
			today=date(2026, 10, 29),
		)
		self.assertFalse(decision["auto_file"])
		self.assertEqual(decision["ai_status"], "Needs Review")

	def test_filename_only_never_auto_files(self):
		decision = decide_inbox(
			{"subject": "Invoices", "confidence": 0.99},
			["Invoices"],
			threshold=0.75,
			year_style="Calendar",
			today=date(2026, 1, 2),
			filename_only=True,
		)
		self.assertFalse(decision["auto_file"])
		self.assertEqual(decision["confidence"], 0.0)

	def test_blueprint_uses_the_existing_building_folder(self):
		children = {
			"Blueprints": ["Boiler House", "Plant Building 1", "QA QC Building", "Site Layouts", "Weighbridge"]
		}
		boiler = decide_inbox(
			{"subject": "Blueprints", "subfolder": None, "title": "Blueprint - Boiler House - Basement", "confidence": 0.9},
			["Blueprints"],
			threshold=0.75,
			year_style="Financial Year",
			today=date(2026, 11, 3),
			subfolders_by_subject=children,
			document_text="Blueprint - Boiler House - Basement Plan.pdf",
		)
		self.assertEqual(boiler["segments"], ["Blueprints", "Boiler House"])
		layouts = resolve_subfolder(None, children["Blueprints"], "Site Layout Plan - MPD Industries")
		self.assertEqual(layouts, "Site Layouts")
		bridge = resolve_subfolder(None, children["Blueprints"], "Weigh Bridge Cabin layout.pdf")
		self.assertEqual(bridge, "Weighbridge")
		warehouse = resolve_subfolder(None, children["Blueprints"], "Warehouse Plan & Section")
		self.assertIsNone(warehouse)

	def test_use_year_without_a_date_does_not_invent_one(self):
		decision = decide_inbox(
			{"subject": "Invoices", "confidence": 0.9, "use_year": True},
			[],
			threshold=0.75,
			year_style="Financial Year",
			today=date(2026, 10, 29),
		)
		self.assertIsNone(decision["year"])
		self.assertEqual(decision["segments"], ["Invoices"])

	def test_subject_is_not_repeated_as_its_own_subfolder(self):
		decision = decide_inbox(
			{
				"subject": "Statutory Documents",
				"subfolder": "Statutory Documents",
				"title": "Factory Licence",
				"confidence": 0.9,
			},
			["Statutory Documents"],
			threshold=0.75,
			year_style="Financial Year",
			today=date(2026, 11, 6),
			subfolders_by_subject={"Statutory Documents": []},
		)
		self.assertEqual(decision["segments"], ["Statutory Documents"])
		self.assertIsNone(decision["subfolder"])

	def test_a_different_subfolder_is_kept(self):
		decision = decide_inbox(
			{"subject": "Blueprints", "subfolder": "Boiler House", "confidence": 0.9},
			["Blueprints"],
			threshold=0.75,
			year_style="Financial Year",
			today=date(2026, 11, 6),
			subfolders_by_subject={"Blueprints": ["Boiler House"]},
		)
		self.assertEqual(decision["segments"], ["Blueprints", "Boiler House"])

	def test_year_folder_is_omitted_unless_requested(self):
		decision = decide_inbox(
			{
				"subject": "Policies",
				"document_date": "2026-06-01",
				"confidence": 0.9,
				"use_year": False,
			},
			[],
			threshold=0.75,
			year_style="Financial Year",
			today=date(2026, 6, 1),
		)
		self.assertEqual(decision["segments"], ["Policies"])
		self.assertIsNone(decision["year"])


class TestReorganizeCandidates(unittest.TestCase):
	def test_reads_files_in_the_folder_and_skips_ones_already_running(self):
		folders = [
			{"name": "docs", "parent": None},
			{"name": "inbox", "parent": "docs"},
			{"name": "invoices", "parent": "docs"},
		]
		files = [
			{"name": "a", "folder": "docs", "status": "Uploaded", "ai_status": ""},
			{"name": "b", "folder": "invoices", "status": "Uploaded", "ai_status": "Needs Review"},
			{"name": "c", "folder": "inbox", "status": "Uploaded", "ai_status": "Queued"},
			{"name": "d", "folder": "other", "status": "Uploaded", "ai_status": ""},
			{"name": "e", "folder": "docs", "status": "Pending", "ai_status": ""},
		]
		self.assertEqual(reorganize_candidates(files, folders, "docs", "inbox"), ["a", "b"])


class TestRouting(unittest.TestCase):
	def test_invoice_selects_the_asset_record_handler(self):
		handler = select_route(
			"Invoice",
			[{"document_type": "Invoice", "handler": APR_HANDLER, "enabled": 1}],
		)
		self.assertEqual(handler, APR_HANDLER)

	def test_disabled_route_is_skipped(self):
		handler = select_route(
			"Invoice",
			[{"document_type": "Invoice", "handler": APR_HANDLER, "enabled": 0}],
		)
		self.assertIsNone(handler)

	def test_s3_url_keeps_the_key(self):
		url = s3_file_url("drive/abc/file.pdf", "file.pdf")
		self.assertIn("key=drive%2Fabc%2Ffile.pdf", url)
		self.assertIn("frappe_s3_attachment.controller.generate_file", url)

import unittest

from mpd_customizations.drive.services.sections import group_library


def _row(name, title, parent=None, inbox=0, kind="General", organise_into=None):
	return {
		"name": name,
		"title": title,
		"parent_drive_folder": parent,
		"is_ai_inbox": inbox,
		"inbox_kind": kind,
		"organise_into": organise_into,
	}


class TestGroupLibrary(unittest.TestCase):
	def test_three_sections(self):
		rows = [
			_row("docs", "Documents"),
			_row("inbox", "Inbox", parent="docs", inbox=1, organise_into="docs"),
			_row("gst", "GST", parent="docs"),
			_row("stat", "Statutory Compliance"),
			_row(
				"cinbox", "Inbox", parent="stat", inbox=1, kind="Statutory Compliance", organise_into="stat"
			),
			_row("fy", "FY 2026-27", parent="stat"),
		]
		grouped = group_library(rows)
		self.assertEqual([row["name"] for row in grouped["drive"]], ["docs"])
		self.assertEqual([row["name"] for row in grouped["ai"]], ["inbox"])
		self.assertEqual([row["name"] for row in grouped["compliance"]], ["stat"])
		self.assertEqual(grouped["membership"]["docs"]["section"], "drive")
		self.assertEqual(grouped["membership"]["gst"]["section"], "drive")
		self.assertEqual(grouped["membership"]["gst"]["anchor"], "docs")
		self.assertEqual(grouped["membership"]["inbox"]["section"], "ai")
		self.assertEqual(grouped["membership"]["inbox"]["anchor"], "inbox")
		self.assertEqual(grouped["membership"]["stat"]["section"], "compliance")
		self.assertEqual(grouped["membership"]["cinbox"]["section"], "compliance")
		self.assertEqual(grouped["membership"]["fy"]["anchor"], "stat")

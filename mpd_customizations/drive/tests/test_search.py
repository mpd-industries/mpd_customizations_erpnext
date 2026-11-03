import unittest

from mpd_customizations.drive.services.search import like_pattern, matches_filename, matches_query


class TestSearchMatch(unittest.TestCase):
	def test_filename_uses_original_name_and_title(self):
		row = {"title": "Tax Invoice", "original_filename": "scan.pdf", "ai_summary": "gst return"}
		self.assertTrue(matches_filename(row, "scan.pdf"))
		self.assertTrue(matches_filename(row, "invoice"))
		self.assertFalse(matches_filename(row, "gst"))

	def test_query_includes_summary(self):
		row = {
			"title": "Tax Invoice",
			"original_filename": "scan.pdf",
			"ai_summary": "gst return",
			"ai_tags": "",
		}
		self.assertTrue(matches_query(row, "gst"))

	def test_like_pattern_escapes_wildcards(self):
		self.assertEqual(like_pattern("100%_done"), "%100\\%\\_done%")

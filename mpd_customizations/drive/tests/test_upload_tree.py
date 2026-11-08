import unittest

from mpd_customizations.drive.services.upload_tree import collect_upload_tree


class TestUploadTree(unittest.TestCase):
	def test_shared_parents_are_created_once_and_junk_is_skipped(self):
		tree = collect_upload_tree(
			[
				"Drawings/a.pdf",
				"Drawings/Boiler/b.pdf",
				"Drawings/Empty/",
				"Drawings/.DS_Store",
				"Drawings/Thumbs.db",
			]
		)
		self.assertEqual(tree["folders"], ["Drawings", "Drawings/Boiler", "Drawings/Empty"])
		self.assertEqual(tree["files"], ["Drawings/a.pdf", "Drawings/Boiler/b.pdf"])

	def test_empty_folder_keeps_its_parents(self):
		tree = collect_upload_tree(["Site/Plans/"])
		self.assertEqual(tree["folders"], ["Site", "Site/Plans"])
		self.assertEqual(tree["files"], [])

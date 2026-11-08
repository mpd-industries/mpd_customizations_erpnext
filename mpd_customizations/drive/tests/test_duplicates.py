import unittest

from mpd_customizations.drive.services.duplicates import duplicate_groups, pick_duplicate, watched_folder_names


def _file(name, digest="h", ok=0, size=10):
	return {
		"name": name,
		"content_hash": digest,
		"duplicate_ok": ok,
		"size": size,
		"is_trashed": 0,
		"status": "Uploaded",
	}


class TestDuplicateGroups(unittest.TestCase):
	def test_duplicate_ok_hides_a_pair_and_a_third_unmarked_copy_shows_it_again(self):
		pair = [_file("a", ok=1), _file("b", ok=1)]
		self.assertEqual(duplicate_groups(pair), [])
		groups = duplicate_groups(pair + [_file("c", ok=0)])
		self.assertEqual(len(groups), 1)
		self.assertEqual({row["name"] for row in groups[0]["files"]}, {"a", "b", "c"})

	def test_two_unmarked_copies_are_a_group_sorted_by_wasted_bytes(self):
		groups = duplicate_groups(
			[
				_file("a", "small", size=5),
				_file("b", "small", size=5),
				_file("c", "big", size=50),
				_file("d", "big", size=50),
			]
		)
		self.assertEqual([group["content_hash"] for group in groups], ["big", "small"])
		self.assertEqual(groups[0]["wasted_bytes"], 50)


class TestWatchedFolders(unittest.TestCase):
	def test_only_a_checked_folder_and_its_contents_are_watched(self):
		folders = [
			{"name": "docs", "parent": None, "check_duplicates": 1},
			{"name": "plans", "parent": "docs", "check_duplicates": 0},
			{"name": "accounts", "parent": None, "check_duplicates": 0},
			{"name": "gst", "parent": "accounts", "check_duplicates": 0},
		]
		self.assertEqual(watched_folder_names(folders), {"docs", "plans"})


class TestUploadDuplicateCheck(unittest.TestCase):
	def test_existing_file_is_returned_unless_the_copy_is_allowed(self):
		existing = [_file("already")]
		self.assertEqual(pick_duplicate(existing, allow_copy=False)["name"], "already")
		self.assertIsNone(pick_duplicate(existing, allow_copy=True))

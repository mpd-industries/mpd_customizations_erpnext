import io
import unittest
import zipfile

from mpd_customizations.drive.services.archive import (
	ZipLimitError,
	build_zip,
	check_zip_request,
	zip_download_name,
	zip_entry_name,
)


class TestZipNames(unittest.TestCase):
	def test_duplicate_titles_get_a_numeric_suffix(self):
		used = set()
		self.assertEqual(zip_entry_name("Plan.pdf", used), "Plan.pdf")
		self.assertEqual(zip_entry_name("Plan.pdf", used), "Plan (2).pdf")
		self.assertEqual(zip_entry_name("Plan.pdf", used), "Plan (3).pdf")

	def test_slashes_in_a_title_stay_inside_one_entry(self):
		self.assertEqual(zip_entry_name("A/B.pdf", set()), "A-B.pdf")

	def test_download_name(self):
		self.assertEqual(zip_download_name("Blueprints"), "Blueprints.zip")
		self.assertEqual(zip_download_name(""), "Drive.zip")

	def test_refuses_too_many_files_and_too_many_bytes(self):
		with self.assertRaises(ZipLimitError):
			check_zip_request([{"size": 1}] * 101)
		with self.assertRaises(ZipLimitError):
			check_zip_request([{"size": 500 * 1024 * 1024 + 1}])

	def test_build_zip_reads_each_object(self):
		store = {"a": b"one", "b": b"two"}
		blob = build_zip(
			[{"title": "One.txt", "size": 3, "key": "a"}, {"title": "One.txt", "size": 3, "key": "b"}],
			store.get,
		)
		with zipfile.ZipFile(io.BytesIO(blob)) as archive:
			self.assertEqual(archive.read("One.txt"), b"one")
			self.assertEqual(archive.read("One (2).txt"), b"two")

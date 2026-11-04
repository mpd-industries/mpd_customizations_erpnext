import unittest
from pathlib import Path

from mpd_customizations.drive.services.s3 import (
	PART_SIZE,
	DriveStorage,
	object_key,
	safe_filename,
	upload_plan,
)


class FakeClient:
	def __init__(self):
		self.calls = []

	def generate_presigned_url(self, operation, Params=None, ExpiresIn=None):
		self.calls.append(("presign", operation))
		return f"https://example.test/{operation}"

	def create_multipart_upload(self, **kwargs):
		self.calls.append(("create_multipart", kwargs["Key"]))
		return {"UploadId": "up-1"}

	def complete_multipart_upload(self, **kwargs):
		self.calls.append(("complete", kwargs["UploadId"]))
		return {}

	def abort_multipart_upload(self, **kwargs):
		self.calls.append(("abort", kwargs["UploadId"]))
		return {}

	def head_object(self, **kwargs):
		self.calls.append(("head", kwargs["Key"]))
		return {"ContentLength": 3}

	def get_object(self, **kwargs):
		self.calls.append(("get", kwargs["Key"]))

		class Body:
			def read(self):
				return b"abc"

		return {"Body": Body()}

	def delete_object(self, **kwargs):
		raise AssertionError("delete_object must not be called")


class TestKeysAndPlans(unittest.TestCase):
	def test_filename_is_stripped(self):
		self.assertEqual(safe_filename("Tax Invoice (final).pdf"), "Tax_Invoice_final.pdf")

	def test_object_key(self):
		self.assertEqual(object_key("drive/", "abc", "a.pdf"), "drive/abc/a.pdf")

	def test_small_file_is_a_single_put(self):
		plan = upload_plan(5 * 1024 * 1024, threshold_mb=100)
		self.assertEqual(plan["mode"], "put")
		self.assertEqual(len(plan["parts"]), 1)

	def test_large_file_is_split_into_10mb_parts(self):
		size = 25 * 1024 * 1024
		plan = upload_plan(size, threshold_mb=10)
		self.assertEqual(plan["mode"], "multipart")
		self.assertEqual(plan["parts"][0]["end"] - plan["parts"][0]["start"], PART_SIZE)
		self.assertEqual(plan["parts"][-1]["end"], size)
		self.assertGreater(len(plan["parts"]), 1)


class TestStorageNeverDeletes(unittest.TestCase):
	def test_operations_do_not_delete(self):
		client = FakeClient()
		storage = DriveStorage(client, "bucket", "drive")
		key = storage.key_for("token", "notes.pdf")
		storage.presign_put(key, "application/pdf")
		upload_id = storage.start_multipart(key, "application/pdf")
		storage.presign_part(key, upload_id, 1)
		storage.complete_multipart(key, upload_id, [{"part_number": 1, "etag": "etag"}])
		storage.abort_multipart(key, upload_id)
		storage.head(key)
		storage.presign_get(key, "notes.pdf")
		storage.read_bytes(key)
		self.assertFalse(any(call[0] == "delete_object" for call in client.calls))
		self.assertFalse(hasattr(DriveStorage, "delete_object"))

	def test_drive_package_has_no_delete_object(self):
		root = Path(__file__).resolve().parents[1]
		for path in root.rglob("*.py"):
			if "tests" in path.parts:
				continue
			text = path.read_text()
			self.assertNotIn("delete_object(", text, path.name)
			self.assertNotIn("DeleteObject", text, path.name)

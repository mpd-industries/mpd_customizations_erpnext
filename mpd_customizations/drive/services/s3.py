"""S3 upload and download helpers.

Drive never deletes finished objects. Aborting a multipart upload only
discards parts that were never completed.
"""

import re
from urllib.parse import quote

PART_SIZE = 10 * 1024 * 1024


def safe_filename(file_name):
	name = (file_name or "file").replace(" ", "_")
	name = re.sub(r"[^0-9A-Za-z._-]", "", name)
	return name or "file"


def object_key(prefix, token, file_name):
	root = (prefix or "drive").strip("/")
	return f"{root}/{token}/{safe_filename(file_name)}"


def upload_plan(size, threshold_mb, part_size=PART_SIZE):
	"""Return put vs multipart and the byte ranges for each part."""
	size = int(size or 0)
	threshold = int(threshold_mb or 0) * 1024 * 1024
	# Files under the threshold, and anything that fits in one part, use a single PUT.
	if size < threshold or size <= part_size:
		return {"mode": "put", "parts": [{"part_number": 1, "start": 0, "end": size}]}
	parts = []
	offset = 0
	number = 1
	while offset < size:
		end = min(offset + part_size, size)
		parts.append({"part_number": number, "start": offset, "end": end})
		offset = end
		number += 1
	return {"mode": "multipart", "parts": parts}


def content_disposition(file_name, inline=False):
	disposition = "inline" if inline else "attachment"
	quoted = quote(file_name or "download")
	return f"{disposition}; filename*=UTF-8''{quoted}"


class DriveStorage:
	"""Thin wrapper around a boto3 S3 client. Finished objects are never removed."""

	def __init__(self, client, bucket, prefix="drive"):
		self.client = client
		self.bucket = bucket
		self.prefix = prefix or "drive"

	def key_for(self, token, file_name):
		return object_key(self.prefix, token, file_name)

	def put_bytes(self, key, data, content_type=None):
		kwargs = {"Bucket": self.bucket, "Key": key, "Body": data}
		if content_type:
			kwargs["ContentType"] = content_type
		return self.client.put_object(**kwargs)

	def presign_put(self, key, content_type=None, expires=3600):
		params = {"Bucket": self.bucket, "Key": key}
		if content_type:
			params["ContentType"] = content_type
		return self.client.generate_presigned_url("put_object", Params=params, ExpiresIn=expires)

	def start_multipart(self, key, content_type=None):
		kwargs = {"Bucket": self.bucket, "Key": key}
		if content_type:
			kwargs["ContentType"] = content_type
		response = self.client.create_multipart_upload(**kwargs)
		return response["UploadId"]

	def presign_part(self, key, upload_id, part_number, expires=3600):
		return self.client.generate_presigned_url(
			"upload_part",
			Params={
				"Bucket": self.bucket,
				"Key": key,
				"UploadId": upload_id,
				"PartNumber": part_number,
			},
			ExpiresIn=expires,
		)

	def complete_multipart(self, key, upload_id, parts):
		ordered = sorted(parts, key=lambda part: part["part_number"])
		return self.client.complete_multipart_upload(
			Bucket=self.bucket,
			Key=key,
			UploadId=upload_id,
			MultipartUpload={
				"Parts": [{"PartNumber": part["part_number"], "ETag": part["etag"]} for part in ordered]
			},
		)

	def abort_multipart(self, key, upload_id):
		if not upload_id:
			return None
		return self.client.abort_multipart_upload(Bucket=self.bucket, Key=key, UploadId=upload_id)

	def head(self, key):
		return self.client.head_object(Bucket=self.bucket, Key=key)

	def presign_get(self, key, file_name=None, inline=False, expires=300):
		params = {"Bucket": self.bucket, "Key": key}
		if file_name:
			params["ResponseContentDisposition"] = content_disposition(file_name, inline=inline)
		return self.client.generate_presigned_url("get_object", Params=params, ExpiresIn=expires)

	def read_bytes(self, key):
		response = self.client.get_object(Bucket=self.bucket, Key=key)
		return response["Body"].read()

	def sha256(self, key):
		"""Hash an object without loading it all into memory."""
		import hashlib

		response = self.client.get_object(Bucket=self.bucket, Key=key)
		body = response["Body"]
		digest = hashlib.sha256()
		while True:
			chunk = body.read(1024 * 1024)
			if not chunk:
				break
			digest.update(chunk)
		return digest.hexdigest()


def get_storage():
	"""Build a DriveStorage from the existing S3 File Attachment settings."""
	import frappe
	from frappe_s3_attachment.controller import S3Operations

	ops = S3Operations()
	prefix = "drive"
	if frappe.db.exists("Drive Settings", "Drive Settings"):
		prefix = frappe.db.get_single_value("Drive Settings", "key_prefix") or "drive"
	return DriveStorage(ops.S3_CLIENT, ops.BUCKET, prefix)

import urllib.parse

import frappe


def is_s3_backed_file(file_doc) -> bool:
	file_url = file_doc.file_url or ""
	if not file_url:
		return False

	if "frappe_s3_attachment" in file_url or "generate_file" in file_url:
		return True

	if file_url.startswith("https://") and file_doc.content_hash and "/" in file_doc.content_hash:
		return True

	return False


def get_s3_key(file_doc) -> str | None:
	file_url = file_doc.file_url or ""

	if "generate_file" in file_url:
		parsed = urllib.parse.urlparse(file_url)
		qs = urllib.parse.parse_qs(parsed.query)
		key = qs.get("key", [None])[0]
		if key:
			return key

	if file_doc.content_hash and is_s3_backed_file(file_doc):
		return file_doc.content_hash

	return None


def read_s3_file_bytes(key: str) -> bytes:
	from frappe_s3_attachment.controller import S3Operations

	response = S3Operations().read_file_from_s3(key)
	return response["Body"].read()

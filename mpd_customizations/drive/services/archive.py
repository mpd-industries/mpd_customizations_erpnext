"""Build a ZIP of Drive files. The caller supplies the bytes for each object."""

import io
import zipfile

MAX_ZIP_FILES = 100
MAX_ZIP_BYTES = 500 * 1024 * 1024


class ZipLimitError(Exception):
	"""The selection is too large to download as one ZIP."""


def check_zip_request(files):
	rows = list(files or [])
	if len(rows) > MAX_ZIP_FILES:
		raise ZipLimitError(f"Select at most {MAX_ZIP_FILES} files")
	total = sum(int(row.get("size") or 0) for row in rows)
	if total > MAX_ZIP_BYTES:
		raise ZipLimitError("These files are larger than 500 MB together")
	return total


def zip_entry_name(title, used):
	"""A unique path inside the ZIP. `used` is the set of names already taken."""
	name = (title or "file").replace("\\", "-").replace("/", "-").strip() or "file"
	if name not in used:
		used.add(name)
		return name
	if "." in name:
		stem, ext = name.rsplit(".", 1)
		ext = "." + ext
	else:
		stem, ext = name, ""
	number = 2
	while True:
		candidate = f"{stem} ({number}){ext}"
		if candidate not in used:
			used.add(candidate)
			return candidate
		number += 1


def zip_download_name(title):
	name = (title or "Drive").replace("\\", "-").replace("/", "-").strip() or "Drive"
	if not name.lower().endswith(".zip"):
		name += ".zip"
	return name


def build_zip(files, read_bytes):
	"""Return ZIP bytes. `files` are dicts with title, size, and key."""
	check_zip_request(files)
	buffer = io.BytesIO()
	used = set()
	with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
		for row in files:
			archive.writestr(zip_entry_name(row.get("title"), used), read_bytes(row.get("key")))
	return buffer.getvalue()

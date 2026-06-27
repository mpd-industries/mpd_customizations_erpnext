from frappe.core.doctype.file.file import File

from mpd_customizations.mpd_base.s3_file import get_s3_key, is_s3_backed_file, read_s3_file_bytes


class CustomFile(File):
	def get_content(self) -> bytes:
		if self.get("content"):
			return super().get_content()

		if is_s3_backed_file(self):
			key = get_s3_key(self)
			if key:
				self._content = read_s3_file_bytes(key)
				return self._content

		return super().get_content()

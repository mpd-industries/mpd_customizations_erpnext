"""Turn a dropped folder into a list of directories and files. No Frappe imports."""

JUNK_NAMES = {".ds_store", "thumbs.db", "desktop.ini"}


def collect_upload_tree(relative_paths):
	"""Return folder paths, parents before children, and the files to upload.

	A path with a trailing slash is an empty folder. Shared parents are listed
	once. OS junk files are left out.
	"""
	folders = []
	files = []
	seen = set()

	def add_folder(path):
		parts = [part for part in path.split("/") if part]
		built = []
		for part in parts:
			built.append(part)
			key = "/".join(built)
			if key in seen:
				continue
			seen.add(key)
			folders.append(key)

	for raw in relative_paths or []:
		text = str(raw or "").replace("\\", "/").strip()
		if not text or text == "/":
			continue
		is_dir = text.endswith("/")
		path = text.strip("/")
		if not path:
			continue
		if is_dir:
			add_folder(path)
			continue
		name = path.split("/")[-1]
		if name.casefold() in JUNK_NAMES:
			continue
		parent = "/".join(path.split("/")[:-1])
		if parent:
			add_folder(parent)
		files.append(path)
	return {"folders": folders, "files": files}

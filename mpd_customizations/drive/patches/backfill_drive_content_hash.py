"""Queue a content-hash backfill after the Drive File fields exist."""


def execute():
	import frappe

	if not frappe.db.has_column("Drive File", "content_hash"):
		return
	from mpd_customizations.drive.services.hashing import queue_hash_backfill

	queue_hash_backfill()

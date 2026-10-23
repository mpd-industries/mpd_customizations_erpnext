import click
import frappe


def after_install():
	_sync_cities()


def after_migrate():
	_migrate_pending_rate_items()
	_sync_cities()


def _sync_cities():
	from mpd_customizations.costing.services.city_sync import sync_cities_from_addresses

	sync_cities_from_addresses()


def _migrate_pending_rate_items():
	"""One-time: clear the old Pending Rate Item table (replaced by Material Rate drafts)."""
	if not frappe.db.table_exists("tabPending Rate Item"):
		return
	count = frappe.db.count("Pending Rate Item")
	if count:
		frappe.db.delete("Pending Rate Item", {})
		frappe.db.commit()
		click.echo(
			f"Cleared {count} legacy Pending Rate Item record(s). Re-run 'Create Pending Rates' to regenerate."
		)

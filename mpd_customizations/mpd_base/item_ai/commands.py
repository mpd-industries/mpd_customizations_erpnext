import click
import frappe


@click.command("recompute-item-labels")
@click.option("--site", required=True, help="Site name")
@click.option(
	"--force",
	is_flag=True,
	default=False,
	help="Recompute all items, not just those with missing/changed labels",
)
def recompute_item_labels(site, force):
	"""Recompute custom_item_label for all Items on a site."""
	frappe.init(site=site)
	frappe.connect()

	try:
		from mpd_customizations.mpd_base.item_ai.backfills import backfill_item_labels

		result = backfill_item_labels(force=force)
		if result is None:
			click.echo("custom_item_label column does not exist yet — run bench migrate first.")
			return

		updated, skipped = result
		click.echo(f"Done. Updated: {updated}  Skipped (already correct): {skipped}")
	finally:
		frappe.destroy()


commands = [recompute_item_labels]

import click
import frappe


@click.command("recompute-item-labels")
@click.option("--site", required=True, help="Site name")
@click.option("--force", is_flag=True, default=False,
              help="Recompute all items, not just those with missing/changed labels")
def recompute_item_labels(site, force):
    """Recompute custom_item_label for all Items on a site."""
    frappe.init(site=site)
    frappe.connect()

    try:
        from mpd_customizations.mpd_base.item_ai.item_hooks import compute_item_label

        if not frappe.db.has_column("Item", "custom_item_label"):
            click.echo("custom_item_label column does not exist yet — run bench migrate first.")
            return

        items = frappe.get_all(
            "Item",
            fields=["name", "item_name", "custom_tally_name", "custom_tally_alias", "custom_item_label"],
        )

        updated = 0
        skipped = 0
        for item in items:
            label = compute_item_label(
                item.item_name,
                item.custom_tally_name,
                item.custom_tally_alias,
            )
            if force or label != (item.custom_item_label or ""):
                frappe.db.set_value("Item", item.name, "custom_item_label", label, update_modified=False)
                updated += 1
            else:
                skipped += 1

        frappe.db.commit()
        click.echo(f"Done. Updated: {updated}  Skipped (already correct): {skipped}")
    finally:
        frappe.destroy()


commands = [recompute_item_labels]

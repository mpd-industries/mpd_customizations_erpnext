import click
import re

import frappe

from mpd_customizations.mpd_base.item_ai.item_hooks import compute_item_label


def backfill_item_labels(force=False, commit=True):
	"""
	Populate custom_item_label for every Item that doesn't have one yet,
	and refresh any item where tally_name/alias may have changed since the
	field was added. Uses direct DB writes (no full save, no hook re-entry).

	With force=True every item is rewritten, matching the
	`bench recompute-item-labels --force` behaviour.

	Returns (updated, skipped).
	"""
	if not frappe.db.has_column("Item", "custom_item_label"):
		return None

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

	if commit and (force or updated):
		frappe.db.commit()

	return updated, skipped


def backfill_item_solids():
	"""
	Populate custom_solids_content_pct for items whose name contains a
	percentage value (e.g. 'Alkyl Phenolic Resin PHE5164, 99%' → 99.0).
	Only fills items where the field is currently NULL or 0 — never
	overwrites a value that was set manually.
	"""
	if not frappe.db.has_column("Item", "custom_solids_content_pct"):
		return

	items = frappe.get_all(
		"Item",
		fields=["name", "item_name", "custom_solids_content_pct"],
	)

	updated = 0
	for item in items:
		if item.custom_solids_content_pct:
			continue
		matches = re.findall(r"(\d+(?:\.\d+)?)\s*%", item.item_name or "")
		if not matches:
			continue
		# take the last percentage in the name — the solids spec is always
		# the trailing descriptor (e.g. "Resin XYZ, 99%")
		pct = float(matches[-1])
		if pct <= 0 or pct > 100:
			continue
		frappe.db.set_value("Item", item.name, "custom_solids_content_pct", pct, update_modified=False)
		updated += 1

	if updated:
		frappe.db.commit()
		click.echo(f"Backfilled custom_solids_content_pct for {updated} item(s).")

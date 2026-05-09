from dataclasses import dataclass, field
from typing import List

import frappe
from frappe.utils import now_datetime

from mpd_customizations.costing.services.rate_source_registry import get_default_registry


@dataclass
class FetchResult:
	has_missing_rates: bool = False
	missing_items: List[str] = field(default_factory=list)
	has_expired_rates: bool = False
	expired_items: List[str] = field(default_factory=list)
	overrides_detected: bool = False
	overrides_changed: List[str] = field(default_factory=list)


class RateFetcher:
	@staticmethod
	def fetch(doc, preserve_overrides: bool = True) -> FetchResult:
		result = FetchResult()
		pricing_dt = now_datetime()

		city = doc.city
		if not city:
			frappe.throw(frappe._("City is required on this document."))

		boms = frappe.get_all(
			"BOM",
			filters={"item": doc.item},
			fields=["name", "item", "quantity", "custom_formulation_id"],
		)

		if not boms:
			frappe.throw(frappe._("No active submitted BOM found for item {0}.").format(doc.item))

		bom_names = [b["name"] for b in boms]
		bom_items = frappe.get_all(
			"BOM Item",
			filters={"parent": ["in", bom_names]},
			fields=["parent", "item_code", "item_name", "qty", "uom"],
		)
		bom_scrap_items = frappe.get_all(
			"BOM Scrap Item",
			filters={"parent": ["in", bom_names]},
			fields=["item_code", "item_name", "stock_uom"],
		)

		# Scrap/byproducts are managed separately — exclude from Material Rate lookup
		scrap_item_codes = {si["item_code"] for si in bom_scrap_items}
		unique_items = list({bi["item_code"] for bi in bom_items} - scrap_item_codes)
		unique_items_set = set(unique_items)
		pairs = [(item_code, city) for item_code in unique_items]

		registry = get_default_registry()
		resolved = registry.batch_resolve(pairs, pricing_dt)

		# Pass 1: update existing child rows in place
		existing_rate_lines = {rl.item: rl for rl in (doc.rate_lines or [])}

		for item_code, existing in existing_rate_lines.items():
			opt = resolved.get((item_code, city))
			if not opt:
				continue

			eq_rate = opt.rate_60d_equivalent  # already computed and stored on Material Rate

			if preserve_overrides:
				is_overridden = (
					round(existing.working_rate or 0, 2) != round(existing.fetched_rate or 0, 2)
				)
				if is_overridden:
					result.overrides_detected = True
					if round(eq_rate, 2) != round(existing.fetched_rate or 0, 2):
						result.overrides_changed.append(item_code)
				else:
					existing.working_rate = eq_rate
					existing.working_supplier_credit_days = opt.supplier_credit_days
			else:
				existing.working_rate = eq_rate
				existing.working_supplier_credit_days = opt.supplier_credit_days

			existing.fetched_rate = eq_rate
			existing.fetched_supplier_credit_days = opt.supplier_credit_days
			existing.rate_freshness = opt.rate_freshness
			existing.supplier = opt.supplier
			existing.rate_source_ref = opt.rate_source_ref
			existing.city = city
			existing.last_working_rate = opt.prev_rate
			existing.market_rate_count = opt.market_rate_count
			existing.market_rate_avg = opt.market_rate_avg
			existing.rate_valid_to = opt.rate_valid_to or ""

		# Pass 2: drop rows for items no longer in BOM
		doc.rate_lines = [rl for rl in doc.rate_lines if rl.item in unique_items_set]

		# Pass 3: append truly new items via doc.append so parent/parentfield are set
		for item_code in unique_items:
			if item_code in existing_rate_lines:
				continue
			opt = resolved.get((item_code, city))
			if not opt:
				continue
			eq_rate = opt.rate_60d_equivalent  # already computed and stored on Material Rate
			doc.append("rate_lines", {
				"item": item_code,
				"city": city,
				"supplier": opt.supplier,
				"rate_source_ref": opt.rate_source_ref,
				"fetched_rate": eq_rate,
				"fetched_supplier_credit_days": opt.supplier_credit_days,
				"rate_freshness": opt.rate_freshness,
				"working_rate": eq_rate,
				"working_supplier_credit_days": opt.supplier_credit_days,
				"last_working_rate": opt.prev_rate,
				"market_rate_count": opt.market_rate_count,
				"market_rate_avg": opt.market_rate_avg,
				"rate_valid_to": opt.rate_valid_to or "",
			})

		# ── Scrap / Byproduct lines sync ────────────────────────────────────────────
		# Rates are entered manually on doc.scrap_lines — no Material Rate lookup.
		# Sync: keep existing rates, add new items, drop obsolete.
		unique_scrap = {si["item_code"]: si for si in bom_scrap_items}
		existing_scrap_map = {sl.item: sl for sl in (doc.scrap_lines or [])}

		doc.scrap_lines = [sl for sl in (doc.scrap_lines or []) if sl.item in unique_scrap]

		for item_code, si in unique_scrap.items():
			if item_code in existing_scrap_map:
				existing = existing_scrap_map[item_code]
				existing.item_name = si["item_name"]
				existing.uom = si["stock_uom"]
			else:
				doc.append("scrap_lines", {
					"item": item_code,
					"item_name": si["item_name"],
					"uom": si["stock_uom"],
					"rate_per_kg": 0.0,
				})

		# Freshness summary
		for item_code in unique_items:
			opt = resolved.get((item_code, city))
			if opt:
				if opt.rate_freshness == "Missing":
					result.has_missing_rates = True
					result.missing_items.append(item_code)
				elif opt.rate_freshness == "Expired":
					result.has_expired_rates = True
					result.expired_items.append(item_code)

		# ── Processing charge ────────────────────────────────────────────────────
		pc = _get_processing_charge(doc.processor, doc.item, pricing_dt)
		existing_pl = doc.processing_lines[0] if doc.processing_lines else None

		if pc:
			if existing_pl:
				if preserve_overrides:
					is_overridden = (
						round(existing_pl.working_charge_per_kg or 0, 2) != round(existing_pl.fetched_charge_per_kg or 0, 2)
						or round(existing_pl.working_freight_per_unit or 0, 2) != round(existing_pl.fetched_freight_per_unit or 0, 2)
						or bool(existing_pl.working_includes_outward_freight) != bool(existing_pl.fetched_includes_outward_freight)
					)
					if is_overridden:
						result.overrides_detected = True
				else:
					existing_pl.working_charge_per_kg = pc.charge_per_kg
					existing_pl.working_freight_per_unit = pc.fg_freight_per_unit or 0
					existing_pl.working_includes_outward_freight = pc.includes_outward_freight

				existing_pl.fetched_charge_per_kg = pc.charge_per_kg
				existing_pl.fetched_freight_per_unit = pc.fg_freight_per_unit or 0
				existing_pl.fetched_includes_outward_freight = pc.includes_outward_freight
				existing_pl.processing_charge_ref = pc["name"]
				existing_pl.processor = doc.processor
			else:
				doc.append("processing_lines", {
					"processor": doc.processor,
					"processing_charge_ref": pc["name"],
					"fetched_charge_per_kg": pc["charge_per_kg"],
					"fetched_freight_per_unit": pc.get("fg_freight_per_unit") or 0,
					"fetched_includes_outward_freight": pc.get("includes_outward_freight"),
					"working_charge_per_kg": pc["charge_per_kg"],
					"working_freight_per_unit": pc.get("fg_freight_per_unit") or 0,
					"working_includes_outward_freight": pc.get("includes_outward_freight"),
				})

		return result


def _get_processing_charge(processor: str, item: str, pricing_dt):
	from frappe.utils import getdate

	pricing_date = getdate(pricing_dt)

	# Fetch all active charges for this processor in one query
	all_charges = frappe.get_all(
		"Processing Charge",
		filters={"processor": processor, "is_active": 1},
		fields=["name", "item", "item_group", "charge_per_kg", "fg_freight_per_unit",
		        "includes_outward_freight", "valid_from", "valid_to"],
	)

	# Filter by validity in Python (avoids duplicate-key or_filters bug)
	valid = [
		pc for pc in all_charges
		if getdate(pc["valid_from"]) <= pricing_date
		and (not pc.get("valid_to") or getdate(pc["valid_to"]) >= pricing_date)
	]

	if not valid:
		return None

	# Item-specific records win outright
	item_specific = [pc for pc in valid if pc.get("item") == item]
	if item_specific:
		return item_specific[0]

	# Group-based: find all that match via nested set, pick most specific (deepest = largest lft)
	item_group_name = frappe.db.get_value("Item", item, "item_group")
	if not item_group_name:
		return None

	item_grp = frappe.db.get_value("Item Group", item_group_name, ["lft", "rgt"], as_dict=True)
	if not item_grp:
		return None

	group_candidates = [pc for pc in valid if pc.get("item_group") and not pc.get("item")]

	# Pre-fetch lft for all candidate groups in one query
	group_names = list({pc["item_group"] for pc in group_candidates})
	if not group_names:
		return None

	group_lft_map = {
		r["name"]: r["lft"]
		for r in frappe.get_all(
			"Item Group",
			filters={"name": ["in", group_names]},
			fields=["name", "lft", "rgt"],
		)
		if r["lft"] <= item_grp["lft"] and r["rgt"] >= item_grp["rgt"]  # ancestor-or-self
	}

	matches = [pc for pc in group_candidates if pc["item_group"] in group_lft_map]
	if not matches:
		return None

	# Most specific = deepest ancestor = largest lft
	matches.sort(key=lambda pc: group_lft_map[pc["item_group"]], reverse=True)
	return matches[0]

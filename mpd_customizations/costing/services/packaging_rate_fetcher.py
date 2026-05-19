from dataclasses import dataclass, field
from typing import List

import frappe
from frappe.utils import getdate, now_datetime


@dataclass
class PackagingFetchResult:
	has_missing_rates: bool = False
	missing_items: List[str] = field(default_factory=list)
	has_expired_rates: bool = False
	expired_items: List[str] = field(default_factory=list)
	overrides_detected: bool = False


class PackagingRateFetcher:
	@staticmethod
	def fetch(doc, preserve_overrides: bool = True) -> PackagingFetchResult:
		result = PackagingFetchResult()
		pricing_date = getdate(now_datetime())

		for line in doc.packaging_lines or []:
			if not line.packaging_material:
				continue

			fill_qty = line.fill_quantity_kg or 0
			rate_record = _get_best_packaging_rate(line.packaging_material, pricing_date)

			if not rate_record:
				line.fetched_rate_per_unit = 0
				line.fetched_rate_per_kg = 0
				line.rate_freshness = "Missing"
				line.packaging_rate_ref = ""
				if not preserve_overrides or not (line.working_rate_per_unit or 0):
					line.working_rate_per_unit = 0
					line.working_rate_per_kg = 0
				result.has_missing_rates = True
				result.missing_items.append(line.packaging_material)
			else:
				fetched_cpu = rate_record["cost_per_unit"]
				fetched_cpk = (fetched_cpu / fill_qty) if fill_qty else 0
				freshness = _compute_freshness(rate_record, pricing_date)

				if preserve_overrides:
					is_overridden = round(line.working_rate_per_unit or 0, 4) != round(line.fetched_rate_per_unit or 0, 4)
					if is_overridden:
						result.overrides_detected = True
					else:
						line.working_rate_per_unit = fetched_cpu
						if fill_qty:
							line.working_rate_per_kg = fetched_cpu / fill_qty
						else:
							line.working_rate_per_kg = 0
				else:
					line.working_rate_per_unit = fetched_cpu
					line.working_rate_per_kg = fetched_cpk

				line.fetched_rate_per_unit = fetched_cpu
				line.fetched_rate_per_kg = fetched_cpk
				line.rate_freshness = freshness
				line.packaging_rate_ref = rate_record["name"]

				if freshness == "Expired":
					result.has_expired_rates = True
					result.expired_items.append(line.packaging_material)

			# Always recompute computed fields from working values
			if fill_qty and (line.working_rate_per_unit or 0):
				line.working_rate_per_kg = (line.working_rate_per_unit or 0) / fill_qty
			line.packages_per_kg = (1.0 / fill_qty) if fill_qty else 0
			line.packaging_cost_per_kg = line.working_rate_per_kg or 0

		return result


def _get_best_packaging_rate(packaging_material: str, pricing_date) -> dict:
	all_rates = frappe.get_all(
		"Packaging Rate",
		filters={"packaging_material": packaging_material, "docstatus": 1},
		fields=["name", "cost_per_unit", "valid_from", "valid_to"],
		order_by="valid_from desc",
	)

	# Current rates (valid today) take priority
	current = [
		r for r in all_rates
		if getdate(r["valid_from"]) <= pricing_date
		and (not r.get("valid_to") or getdate(r["valid_to"]) >= pricing_date)
	]
	if current:
		return current[0]

	# Expired but most recent
	expired = [r for r in all_rates if r.get("valid_to") and getdate(r["valid_to"]) < pricing_date]
	if expired:
		expired.sort(key=lambda r: r["valid_to"], reverse=True)
		return expired[0]

	return None


def _compute_freshness(rate_record: dict, pricing_date) -> str:
	if not rate_record.get("valid_to"):
		return "Current"
	if getdate(rate_record["valid_to"]) < pricing_date:
		return "Expired"
	return "Current"

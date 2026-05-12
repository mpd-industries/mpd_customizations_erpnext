from dataclasses import dataclass, field
from typing import List, Optional

import frappe
from frappe.utils import getdate, now_datetime


@dataclass
class FreightFetchResult:
	has_missing_rates: bool = False
	missing_destinations: List[str] = field(default_factory=list)
	has_expired_rates: bool = False
	expired_destinations: List[str] = field(default_factory=list)
	overrides_detected: bool = False


class FreightRateFetcher:
	@staticmethod
	def fetch(doc, preserve_overrides: bool = True) -> FreightFetchResult:
		result = FreightFetchResult()
		pricing_date = getdate(now_datetime())
		source_address = _get_source_address(doc)

		for line in doc.delivery_lines or []:
			if not line.destination_address:
				continue

			# Keep source fields in sync with the processor (survives re-evaluations)
			if source_address and not line.source_address:
				line.source_address = source_address
			if getattr(doc, "processor", None) and not line.source_city:
				line.source_city = frappe.db.get_value("Processor", doc.processor, "city") or ""

			mode = line.transport_mode or "Barrels"
			incoterms = getattr(line, "incoterms", "") or ""
			rate_record = _get_best_freight_rate(
				source_address,
				line.destination_address,
				mode,
				pricing_date,
				incoterms,
			)
			dest_label = f"{line.destination_city or line.destination_address} ({mode})"

			if not rate_record:
				line.fetched_freight_per_kg = 0
				line.fetched_forex_rate = 0
				line.fetched_currency = ""
				line.rate_freshness = "Missing"
				line.freight_rate_ref = ""
				if not preserve_overrides or not (line.working_freight_per_kg or 0):
					line.working_freight_per_kg = 0
					line.working_forex_rate = 0
				result.has_missing_rates = True
				result.missing_destinations.append(dest_label)
			else:
				freshness = _compute_freshness(rate_record, pricing_date)

				if preserve_overrides:
					is_overridden = (
						round(line.working_freight_per_kg or 0, 4) != round(line.fetched_freight_per_kg or 0, 4)
					)
					if is_overridden:
						result.overrides_detected = True
					else:
						line.working_freight_per_kg = rate_record["freight_per_kg"]
						line.working_forex_rate = rate_record.get("forex_rate") or 0
						line.working_currency = rate_record.get("currency") or ""
				else:
					line.working_freight_per_kg = rate_record["freight_per_kg"]
					line.working_forex_rate = rate_record.get("forex_rate") or 0
					line.working_currency = rate_record.get("currency") or ""

				line.fetched_freight_per_kg = rate_record["freight_per_kg"]
				line.fetched_forex_rate = rate_record.get("forex_rate") or 0
				line.fetched_currency = rate_record.get("currency") or ""
				line.rate_freshness = freshness
				line.freight_rate_ref = rate_record["name"]

				if freshness == "Expired":
					result.has_expired_rates = True
					result.expired_destinations.append(dest_label)

		return result


def _get_source_address(doc) -> str:
	if getattr(doc, "processor", None):
		addr = frappe.db.get_value("Processor", doc.processor, "address")
		if addr:
			return addr
	return ""


def _get_best_freight_rate(
	source_address: str,
	destination_address: str,
	transport_mode: str,
	pricing_date,
	incoterms: str = "",
) -> Optional[dict]:
	"""
	Fetch the best active rate for this route+mode+incoterms.
	Current rates take priority over expired; most recent valid_from wins within each pool.
	If incoterms is specified, rates with matching incoterms are preferred; rates with blank
	incoterms are used as fallback.
	"""
	all_rates = frappe.get_all(
		"Freight Rate",
		filters={
			"source_address": source_address,
			"destination_address": destination_address,
			"transport_mode": transport_mode,
			"docstatus": 1,
		},
		fields=["name", "incoterms", "freight_per_kg", "forex_rate", "currency", "valid_from", "valid_to"],
		order_by="valid_from desc",
	)

	def is_valid(r):
		return (
			getdate(r["valid_from"]) <= pricing_date
			and (not r.get("valid_to") or getdate(r["valid_to"]) >= pricing_date)
		)

	current = [r for r in all_rates if is_valid(r)]
	expired = sorted(
		[r for r in all_rates if r.get("valid_to") and getdate(r["valid_to"]) < pricing_date],
		key=lambda r: r["valid_to"],
		reverse=True,
	)

	for pool in (current, expired):
		if incoterms:
			# Prefer exact incoterms match, fall back to blank incoterms
			match = next((r for r in pool if r.get("incoterms") == incoterms), None)
			if match:
				return match
			match = next((r for r in pool if not r.get("incoterms")), None)
			if match:
				return match
		else:
			match = next(iter(pool), None)
			if match:
				return match

	return None


def _compute_freshness(rate_record: dict, pricing_date) -> str:
	if not rate_record.get("valid_to"):
		return "Current"
	if getdate(rate_record["valid_to"]) < pricing_date:
		return "Expired"
	return "Current"

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
		customer = getattr(doc, "customer", "") or ""
		customer_product_ref = getattr(doc, "customer_product_ref", "") or ""

		for line in doc.delivery_lines or []:
			if not line.destination_address:
				continue

			mode = line.transport_mode or "Barrels"
			rate_record = _get_best_freight_rate(
				source_address,
				line.destination_address,
				mode,
				customer,
				customer_product_ref,
				pricing_date,
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

			line.delivery_cost_per_kg_inr = line.working_freight_per_kg or 0

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
	customer: str,
	customer_product_ref: str,
	pricing_date,
) -> Optional[dict]:
	"""
	Fetch the most specific active rate for this lane+mode.
	Specificity order (highest to lowest):
	  1. customer + customer_product match
	  2. customer match (no product restriction)
	  3. General lane rate (no customer, no product)
	Expired rates are used as fallback in the same priority order.
	"""
	all_rates = frappe.get_all(
		"Freight Rate",
		filters={
			"source_address": source_address,
			"destination_address": destination_address,
			"transport_mode": transport_mode,
			"docstatus": 1,
		},
		fields=["name", "customer", "customer_product", "freight_per_kg", "forex_rate", "currency", "valid_from", "valid_to"],
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
		# Tier 1: exact customer + product match
		if customer and customer_product_ref:
			match = next(
				(r for r in pool if r.get("customer") == customer and r.get("customer_product") == customer_product_ref),
				None,
			)
			if match:
				return match

		# Tier 2: customer match, no product restriction
		if customer:
			match = next(
				(r for r in pool if r.get("customer") == customer and not r.get("customer_product")),
				None,
			)
			if match:
				return match

		# Tier 3: general lane rate
		match = next(
			(r for r in pool if not r.get("customer") and not r.get("customer_product")),
			None,
		)
		if match:
			return match

	return None


def _compute_freshness(rate_record: dict, pricing_date) -> str:
	if not rate_record.get("valid_to"):
		return "Current"
	if getdate(rate_record["valid_to"]) < pricing_date:
		return "Expired"
	return "Current"

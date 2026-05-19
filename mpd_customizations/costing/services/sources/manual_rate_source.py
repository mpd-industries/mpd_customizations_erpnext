from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import frappe
from frappe.utils import getdate

from mpd_customizations.costing.services.rate_option import RateOption
from mpd_customizations.costing.services.sources.base import BaseRateSource


class ManualRateSource(BaseRateSource):
	source_type = "Manual"
	priority = 10

	def can_resolve(self, item: str, city: str, pricing_dt: datetime) -> bool:
		return True

	def resolve(self, item: str, city: str, pricing_dt: datetime) -> List[RateOption]:
		result = self.batch_resolve([(item, city)], pricing_dt)
		return result.get((item, city), [])

	def batch_resolve(
		self,
		pairs: List[Tuple[str, str]],
		pricing_dt: datetime,
	) -> Dict[Tuple[str, str], List[RateOption]]:
		if not pairs:
			return {}

		items = list({p[0] for p in pairs})
		cities = list({p[1] for p in pairs})

		records = frappe.get_all(
			"Material Rate",
			filters={"item": ["in", items], "city": ["in", cities], "docstatus": 1},
			fields=[
				"name",
				"item",
				"city",
				"supplier",
				"delivered_rate",
				"rate_60d_equivalent",
				"credit_days",
				"lead_time_days",
				"valid_from",
				"valid_to",
				"rate_type",
				"ex_works_rate",
				"uom",
			],
		)

		grouped: Dict[Tuple[str, str], list] = defaultdict(list)
		for r in records:
			grouped[(r["item"], r["city"])].append(r)

		supplier_history_count: Dict[Tuple[str, str, str], int] = defaultdict(int)
		for r in records:
			supplier_history_count[(r["item"], r["city"], r.get("supplier") or "")] += 1

		result = {}
		for pair in pairs:
			result[pair] = self._resolve_pair(
				pair[0], pair[1], pricing_dt, grouped[pair], supplier_history_count
			)
		return result

	def _resolve_pair(
		self,
		item: str,
		city: str,
		pricing_dt: datetime,
		records: list,
		supplier_history_count: Dict,
	) -> List[RateOption]:
		current = []
		expired = []

		pricing_date = pricing_dt.date() if hasattr(pricing_dt, "date") else pricing_dt
		for r in records:
			vf = getdate(r["valid_from"])
			vt = getdate(r["valid_to"]) if r.get("valid_to") else None
			is_current = vf <= pricing_date and (vt is None or vt >= pricing_date)
			if is_current:
				current.append(r)
			elif vt and vt < pricing_date:
				expired.append(r)

		current.sort(key=lambda r: r.get("delivered_rate") or 0)
		expired.sort(key=lambda r: r["valid_from"], reverse=True)

		if not current and not expired:
			return [
				RateOption(
					item=item,
					city=city,
					delivered_rate=0.0,
					valid_from=pricing_dt,
					rate_freshness="Missing",
					confidence_score=0.0,
				)
			]

		# Market intelligence — computed once, attached to the best option only
		prev_rate = (expired[0].get("rate_60d_equivalent") or expired[0].get("delivered_rate") or 0.0) if expired else 0.0
		market_rate_count = len(current)
		market_rate_avg = (
			sum(r.get("rate_60d_equivalent") or r.get("delivered_rate") or 0.0 for r in current) / len(current)
			if current else 0.0
		)
		rate_valid_to = str(current[0].get("valid_to")) if current and current[0].get("valid_to") else None

		options = []
		all_sorted = current + expired
		for idx, r in enumerate(all_sorted):
			freshness = "Current" if r in current else "Expired"
			score = self._confidence_score(r, pricing_dt, supplier_history_count)
			second_best_supplier = all_sorted[1].get("supplier") if idx == 0 and len(all_sorted) > 1 else None
			second_best_rate = all_sorted[1].get("delivered_rate", 0.0) if idx == 0 and len(all_sorted) > 1 else 0.0
			options.append(
				RateOption(
					item=item,
					city=city,
					supplier=r.get("supplier"),
					rate_source_ref=r.get("name"),
					delivered_rate=r.get("delivered_rate") or 0.0,
					rate_60d_equivalent=r.get("rate_60d_equivalent") or r.get("delivered_rate") or 0.0,
					supplier_credit_days=r.get("credit_days") or 0,
					lead_time_days=r.get("lead_time_days"),
					valid_from=r["valid_from"],
					valid_to=r.get("valid_to"),
					rate_freshness=freshness,
					confidence_score=score,
					second_best_supplier=second_best_supplier,
					second_best_rate=second_best_rate,
					prev_rate=prev_rate if idx == 0 else 0.0,
					market_rate_count=market_rate_count if idx == 0 else 0,
					market_rate_avg=market_rate_avg if idx == 0 else 0.0,
					rate_valid_to=rate_valid_to if idx == 0 else None,
				)
			)
		return options

	def _confidence_score(self, record, pricing_dt: datetime, supplier_history_count: Dict) -> float:
		score = 50.0
		if record.get("supplier_quotation_ref"):
			score += 20
		pricing_date = pricing_dt.date() if hasattr(pricing_dt, "date") else pricing_dt
		threshold = pricing_date - timedelta(days=30)
		vf = record.get("valid_from")
		if vf and getdate(vf) >= threshold:
			score += 20
		key = (record.get("item", ""), record.get("city", ""), record.get("supplier") or "")
		if supplier_history_count.get(key, 0) >= 3:
			score += 10
		if record.get("rate_type") == "All-In Delivered" and not record.get("ex_works_rate"):
			score -= 30
		return max(0.0, min(100.0, score))

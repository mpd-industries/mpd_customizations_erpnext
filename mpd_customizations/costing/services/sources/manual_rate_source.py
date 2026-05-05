import frappe
from typing import List, Tuple, Dict
from collections import defaultdict
from datetime import datetime
from frappe.utils.data import get_datetime
from mpd_customizations.costing.services.sources.base import BaseRateSource
from mpd_customizations.costing.services.rate_option import RateOption

class ManualRateSource(BaseRateSource):
    source_type = "Manual"
    priority = 10

    def can_resolve(self, item: str, city: str, pricing_dt: datetime) -> bool:
        return True

    def resolve(self, item: str, city: str, pricing_dt: datetime) -> List[RateOption]:
        return self.batch_resolve([(item, city)], pricing_dt).get((item, city), [])

    def batch_resolve(self, pairs: List[Tuple[str, str]], pricing_dt: datetime) -> Dict[Tuple[str, str], List[RateOption]]:
        if not pairs:
            return {}

        items = list({p[0] for p in pairs})
        cities = list({p[1] for p in pairs})

        records = frappe.get_all(
            "Material Rate",
            filters={
                "item": ["in", items],
                "city": ["in", cities]
            },
            fields=[
                "name", "item", "city", "supplier", "delivered_rate",
                "credit_days", "lead_time_days", "valid_from", "valid_to",
                "is_active", "rate_type", "ex_works_rate"
            ]
        )

        grouped = defaultdict(list)
        for r in records:
            grouped[(r.item, r.city)].append(r)

        result = {}
        for item, city in pairs:
            group = grouped.get((item, city), [])
            
            current_recs = []
            expired_recs = []
            
            for r in group:
                if not r.is_active:
                    continue
                v_from = get_datetime(r.valid_from).replace(tzinfo=None)
                v_to = get_datetime(r.valid_to).replace(tzinfo=None) if r.valid_to else None
                
                if v_from > pricing_dt:
                    continue

                if v_to is None or v_to >= pricing_dt:
                    current_recs.append(r)
                else:
                    expired_recs.append(r)
            
            current_recs.sort(key=lambda x: x.delivered_rate or 0)
            expired_recs.sort(key=lambda x: get_datetime(x.valid_from).replace(tzinfo=None), reverse=True)
            
            if current_recs:
                best = current_recs[0]
                freshness = "Current"
                second_best = current_recs[1] if len(current_recs) > 1 else None
            elif expired_recs:
                best = expired_recs[0]
                freshness = "Expired"
                second_best = expired_recs[1] if len(expired_recs) > 1 else None
            else:
                best = None
                freshness = "Missing"
                second_best = None

            if not best:
                result[(item, city)] = [RateOption(
                    item=item,
                    city=city,
                    delivered_rate=0.0,
                    rate_freshness="Missing",
                    confidence_score=0.0
                )]
                continue

            conf_score = 50.0
            v_from = get_datetime(best.valid_from).replace(tzinfo=None)
            if (pricing_dt - v_from).days <= 30:
                conf_score += 20.0
            
            supplier_hist = sum(1 for r in group if r.supplier == best.supplier)
            if supplier_hist >= 3:
                conf_score += 10.0
            
            if best.rate_type == "All-In Delivered" and not best.ex_works_rate:
                conf_score -= 30.0
            
            conf_score = max(0.0, min(100.0, conf_score))

            ro = RateOption(
                item=item,
                city=city,
                delivered_rate=best.delivered_rate or 0.0,
                rate_freshness=freshness,
                supplier=best.supplier,
                rate_source_ref=best.name,
                supplier_credit_days=best.credit_days or 0,
                lead_time_days=best.lead_time_days,
                valid_from=v_from,
                valid_to=get_datetime(best.valid_to).replace(tzinfo=None) if best.valid_to else None,
                confidence_score=conf_score
            )
            
            if second_best:
                ro.second_best_supplier = second_best.supplier
                ro.second_best_rate = second_best.delivered_rate or 0.0
                
            result[(item, city)] = [ro]

        return result

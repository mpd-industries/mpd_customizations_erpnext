from typing import List, Tuple, Dict
from datetime import datetime
from mpd_customizations.costing.services.sources.base import BaseRateSource
from mpd_customizations.costing.services.sources.manual_rate_source import ManualRateSource
from mpd_customizations.costing.services.rate_option import RateOption

class RateSourceRegistry:
    def __init__(self, sources: List[BaseRateSource]):
        self.sources = sorted(sources, key=lambda x: x.priority)

    def batch_resolve(self, pairs: List[Tuple[str, str]], pricing_dt: datetime) -> Dict[Tuple[str, str], RateOption]:
        merged_results = {pair: [] for pair in pairs}
        
        for source in self.sources:
            source_results = source.batch_resolve(pairs, pricing_dt)
            for pair, options in source_results.items():
                merged_results[pair].extend(options)
                
        final_result = {}
        for pair, options in merged_results.items():
            if not options:
                final_result[pair] = RateOption(
                    item=pair[0], city=pair[1], delivered_rate=0.0, rate_freshness="Missing", confidence_score=0.0
                )
                continue
                
            current = [o for o in options if o.rate_freshness == "Current"]
            expired = [o for o in options if o.rate_freshness == "Expired"]
            missing = [o for o in options if o.rate_freshness == "Missing"]
            
            current.sort(key=lambda x: x.delivered_rate)
            expired.sort(key=lambda x: x.delivered_rate)
            
            sorted_options = current + expired + missing
            best = sorted_options[0]
            
            if len(sorted_options) > 1 and sorted_options[1].rate_freshness != "Missing":
                best.second_best_supplier = sorted_options[1].supplier
                best.second_best_rate = sorted_options[1].delivered_rate
                
            final_result[pair] = best
            
        return final_result

def get_default_registry() -> RateSourceRegistry:
    return RateSourceRegistry(sources=[ManualRateSource()])

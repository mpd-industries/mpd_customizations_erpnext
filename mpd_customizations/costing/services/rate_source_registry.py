from datetime import datetime
from typing import Dict, List, Tuple

from mpd_customizations.costing.services.rate_option import RateOption
from mpd_customizations.costing.services.sources.base import BaseRateSource


_FRESHNESS_ORDER = {"Current": 0, "Expired": 1, "Missing": 2}


class RateSourceRegistry:
	def __init__(self, sources: List[BaseRateSource]):
		self._sources = sorted(sources, key=lambda s: s.priority)

	def batch_resolve(
		self,
		pairs: List[Tuple[str, str]],
		pricing_dt: datetime,
	) -> Dict[Tuple[str, str], RateOption]:
		all_options: Dict[Tuple[str, str], List[RateOption]] = {p: [] for p in pairs}

		for source in self._sources:
			source_result = source.batch_resolve(pairs, pricing_dt)
			for pair, options in source_result.items():
				all_options[pair].extend(options)

		result = {}
		for pair, options in all_options.items():
			if not options:
				from mpd_customizations.costing.services.rate_option import RateOption as RO
				result[pair] = RO(
					item=pair[0],
					city=pair[1],
					delivered_rate=0.0,
					valid_from=pricing_dt,
					rate_freshness="Missing",
					confidence_score=0.0,
				)
				continue

			options.sort(key=lambda o: (_FRESHNESS_ORDER.get(o.rate_freshness, 9), o.delivered_rate))
			best = options[0]
			if len(options) > 1:
				best.second_best_supplier = options[1].supplier
				best.second_best_rate = options[1].delivered_rate
			result[pair] = best

		return result


def get_default_registry() -> RateSourceRegistry:
	from mpd_customizations.costing.services.sources.manual_rate_source import ManualRateSource
	return RateSourceRegistry([ManualRateSource()])

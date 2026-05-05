from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Tuple, Dict
from mpd_customizations.costing.services.rate_option import RateOption

class BaseRateSource(ABC):
    source_type: str = ""
    priority: int = 100

    @abstractmethod
    def can_resolve(self, item: str, city: str, pricing_dt: datetime) -> bool:
        pass

    @abstractmethod
    def resolve(self, item: str, city: str, pricing_dt: datetime) -> List[RateOption]:
        pass

    def batch_resolve(self, pairs: List[Tuple[str, str]], pricing_dt: datetime) -> Dict[Tuple[str, str], List[RateOption]]:
        result = {}
        for item, city in pairs:
            if self.can_resolve(item, city, pricing_dt):
                result[(item, city)] = self.resolve(item, city, pricing_dt)
            else:
                result[(item, city)] = []
        return result

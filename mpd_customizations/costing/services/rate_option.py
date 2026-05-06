from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class RateOption:
	item: str
	city: str
	delivered_rate: float
	valid_from: datetime
	rate_freshness: str
	supplier: Optional[str] = None
	rate_source_ref: Optional[str] = None
	supplier_credit_days: int = 0
	lead_time_days: Optional[int] = None
	valid_to: Optional[datetime] = None
	confidence_score: float = 50.0
	second_best_supplier: Optional[str] = None
	second_best_rate: float = 0.0

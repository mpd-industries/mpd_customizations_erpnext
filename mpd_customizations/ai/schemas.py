"""Pydantic models for LLM structured outputs (LiteLLM response_format)."""

from typing import Any

from pydantic import BaseModel, Field, field_validator


class ReviewOutput(BaseModel):
	"""Matches the JSON contract used by master-data review prompts."""

	decision: str = Field(
		..., description='Either "Approved" or "Flagged" (case-insensitive).'
	)
	confidence: int = Field(..., ge=0, le=100)
	brief: str = ""
	issues: list[str] = Field(default_factory=list)
	checks: dict[str, Any] = Field(default_factory=dict)

	model_config = {"extra": "ignore"}

	@field_validator("confidence", mode="before")
	@classmethod
	def coerce_confidence(cls, v):
		if v is None:
			return 0
		try:
			c = int(round(float(v)))
			return max(0, min(100, c))
		except (TypeError, ValueError):
			return 0

	@field_validator("issues", mode="before")
	@classmethod
	def coerce_issues(cls, v):
		if v is None:
			return []
		if isinstance(v, str):
			return [v]
		return v

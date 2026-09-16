"""Claim summaries for the combined model landing page."""

from typing import Literal

from pydantic import BaseModel


class ModelRecommendation(BaseModel):
    Predictions: Literal["High", "Low"] | None
    Action: str | None


class LandingClaim(BaseModel):
    claim_number: str
    fraud: list[ModelRecommendation]
    litigation: list[ModelRecommendation]
    severity: list[ModelRecommendation]
    subrogation: list[ModelRecommendation]

"""Response models for the Third Party Auto claim dashboard."""

from typing import Any

from pydantic import BaseModel, Field


class DashboardIndicators(BaseModel):
    """Power BI-equivalent claim availability and status indicators."""

    assigned: str
    dcw: str
    cts: str
    smart_features: str
    watchlist: str
    carpe: str
    ies_bills: str
    iso_match: str


class ThirdPartyAutoDashboard(BaseModel):
    """All read-only dashboard sections for one normalized claim number."""

    claim_number: str
    indicators: DashboardIndicators
    edw: list[dict[str, Any]] = Field(default_factory=list)
    cts: list[dict[str, Any]] = Field(default_factory=list)
    smart_features: list[dict[str, Any]] = Field(default_factory=list)
    watchlist: list[dict[str, Any]] = Field(default_factory=list)
    carpe: list[dict[str, Any]] = Field(default_factory=list)
    ies_bills: list[dict[str, Any]] = Field(default_factory=list)
    alert_reasons: list[str] = Field(default_factory=list)
    game_summary: list[dict[str, Any]] = Field(default_factory=list)

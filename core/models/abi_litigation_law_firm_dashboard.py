"""Response models for the ABI Litigation law firm dashboard."""

from typing import Any

from pydantic import BaseModel, Field


class LawFirmKpis(BaseModel):
    claim_count: int
    legal_matter_count: int
    legal_matter_open_count: int
    settlement_percentage: float
    trial_percentage: float
    litigation_open_percentage: float
    litigation_duration_days: float | None
    claim_duration_days: float | None


class LawFirmDashboard(BaseModel):
    law_firm_name: str
    kpis: LawFirmKpis
    claim_info: list[dict[str, Any]] = Field(default_factory=list)
    notes: list[dict[str, Any]] = Field(default_factory=list)
    resolution_counts: list[dict[str, Any]] = Field(default_factory=list)
    settlement_bins: list[dict[str, Any]] = Field(default_factory=list)
    line_of_business_counts: list[dict[str, Any]] = Field(default_factory=list)
    jurisdiction_counts: list[dict[str, Any]] = Field(default_factory=list)
    annual_rates: list[dict[str, Any]] = Field(default_factory=list)

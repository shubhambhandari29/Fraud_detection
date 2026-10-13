"""Response models for the ABI Litigation claim dashboard."""

from typing import Any

from pydantic import BaseModel, Field


class AbiLitigationDashboard(BaseModel):
    """Power BI-equivalent Litigation data for one claim-feature number."""

    claim_number: str
    edw: list[dict[str, Any]] = Field(default_factory=list)
    game_summary: list[dict[str, Any]] = Field(default_factory=list)

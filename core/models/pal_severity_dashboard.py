"""Response model for the PAL Severity claim dashboard."""

from typing import Any

from pydantic import BaseModel, Field


class PalSeverityDashboard(BaseModel):
    """Power BI claim details and Carpe alerts for one claim feature."""

    claim_number: str
    carpe_available: str
    edw: list[dict[str, Any]] = Field(default_factory=list)
    carpe: list[dict[str, Any]] = Field(default_factory=list)

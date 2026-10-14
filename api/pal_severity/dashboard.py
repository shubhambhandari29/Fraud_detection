"""PAL Severity claim dashboard API."""

from fastapi import APIRouter, Depends

from core.models.pal_severity_dashboard import PalSeverityDashboard
from services.auth_service import get_current_user_from_token
from services.pal_severity.dashboard_service import get_dashboard


router = APIRouter(dependencies=[Depends(get_current_user_from_token)])


@router.get("/{claim_number}", response_model=PalSeverityDashboard)
async def get_claim_dashboard(claim_number: str) -> PalSeverityDashboard:
    return await get_dashboard(claim_number)

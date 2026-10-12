"""Third Party Auto claim dashboard API."""

from fastapi import APIRouter, Depends

from core.models.third_party_auto_dashboard import ThirdPartyAutoDashboard
from services.auth_service import get_current_user_from_token
from services.third_party_auto.dashboard_service import get_dashboard


router = APIRouter(dependencies=[Depends(get_current_user_from_token)])


@router.get("/{claim_number}", response_model=ThirdPartyAutoDashboard)
async def get_claim_dashboard(claim_number: str) -> ThirdPartyAutoDashboard:
    return await get_dashboard(claim_number)

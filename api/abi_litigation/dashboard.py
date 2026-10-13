"""ABI Litigation claim dashboard API."""

from fastapi import APIRouter, Depends

from core.models.abi_litigation_dashboard import AbiLitigationDashboard
from services.abi_litigation.dashboard_service import get_dashboard
from services.auth_service import get_current_user_from_token


router = APIRouter(dependencies=[Depends(get_current_user_from_token)])


@router.get("/{claim_number}", response_model=AbiLitigationDashboard)
async def get_claim_dashboard(claim_number: str) -> AbiLitigationDashboard:
    return await get_dashboard(claim_number)

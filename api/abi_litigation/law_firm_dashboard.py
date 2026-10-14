"""ABI Litigation law firm dashboard API."""

from fastapi import APIRouter, Depends

from core.models.abi_litigation_law_firm_dashboard import LawFirmDashboard
from services.abi_litigation.law_firm_dashboard_service import get_law_firm_dashboard
from services.auth_service import get_current_user_from_token


router = APIRouter(dependencies=[Depends(get_current_user_from_token)])


@router.get("/{law_firm_name}", response_model=LawFirmDashboard)
async def get_dashboard(law_firm_name: str) -> LawFirmDashboard:
    return await get_law_firm_dashboard(law_firm_name)

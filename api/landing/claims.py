"""Read selected claims across all four models."""

from fastapi import APIRouter, Depends

from core.models.landing import LandingClaim
from services.auth_service import get_current_user_from_token
from services.landing.claims_service import get_claims


router = APIRouter(dependencies=[Depends(get_current_user_from_token)])


@router.get("/", response_model=list[LandingClaim])
async def get_landing_claims() -> list[LandingClaim]:
    """Return every selected model row, grouped by normalized claim number."""
    return await get_claims()

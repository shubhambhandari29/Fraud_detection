"""User roster API routes."""

from typing import Any

from fastapi import APIRouter, Depends

from core.models.common import WriteResult
from services.auth_service import get_current_user_from_token
from services.third_party_auto.user_roster_service import (
    get_user_roster as get_user_roster_service,
)
from services.third_party_auto.user_roster_service import (
    upsert_user_roster as upsert_user_roster_service,
)


router = APIRouter(dependencies=[Depends(get_current_user_from_token)])


@router.get("/")
async def get_user_roster() -> list[dict[str, Any]]:
    return await get_user_roster_service()


@router.post("/upsert", response_model=WriteResult)
async def upsert_user_roster(payload: dict[str, Any]) -> dict[str, Any]:
    return await upsert_user_roster_service([payload])

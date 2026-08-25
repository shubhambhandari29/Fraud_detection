"""User roster API routes."""

from typing import Any

from fastapi import APIRouter, Depends, Query

from core.models.common import WriteResult
from services.auth_service import get_current_user_from_token
from services.user_roster_service import get_user_roster as get_user_roster_service
from services.user_roster_service import upsert_user_roster as upsert_user_roster_service


router = APIRouter(dependencies=[Depends(get_current_user_from_token)])


@router.get("/")
async def get_user_roster(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    return await get_user_roster_service(limit, offset)


@router.post("/upsert", response_model=WriteResult)
async def upsert_user_roster(payload: dict[str, Any]) -> dict[str, Any]:
    return await upsert_user_roster_service([payload])

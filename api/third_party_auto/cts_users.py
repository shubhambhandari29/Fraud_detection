"""CTS users API routes."""

from typing import Any

from fastapi import APIRouter, Depends

from core.models.common import WriteResult
from services.auth_service import get_current_user_from_token
from services.third_party_auto.cts_users_service import (
    get_cts_users as get_cts_users_service,
)
from services.third_party_auto.cts_users_service import (
    upsert_cts_users as upsert_cts_users_service,
)


router = APIRouter(dependencies=[Depends(get_current_user_from_token)])


@router.get("/")
async def get_cts_users() -> list[dict[str, Any]]:
    return await get_cts_users_service()


@router.post("/upsert", response_model=WriteResult)
async def upsert_cts_users(payload: dict[str, Any]) -> dict[str, Any]:
    return await upsert_cts_users_service([payload])

"""CTS users API routes."""

from typing import Any

from fastapi import APIRouter, Depends, Query

from core.models.common import UpsertRequest, WriteResult
from services.auth_service import get_current_user_from_token
from services.cts_users_service import get_cts_users as get_cts_users_service
from services.cts_users_service import upsert_cts_users as upsert_cts_users_service


router = APIRouter(dependencies=[Depends(get_current_user_from_token)])


@router.get("/")
async def get_cts_users(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    return await get_cts_users_service(limit, offset)


@router.post("/upsert", response_model=WriteResult)
async def upsert_cts_users(payload: UpsertRequest) -> dict[str, Any]:
    return await upsert_cts_users_service(payload.records)

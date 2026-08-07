"""Analyst roster API routes."""

from typing import Any

from fastapi import APIRouter, Depends, Query

from core.models.common import UpsertRequest, WriteResult
from services.analysts_service import get_analysts as get_analysts_service
from services.analysts_service import upsert_analysts as upsert_analysts_service
from services.auth_service import get_current_user_from_token


router = APIRouter(dependencies=[Depends(get_current_user_from_token)])


@router.get("/")
async def get_analysts(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    return await get_analysts_service(limit, offset)


@router.post("/upsert", response_model=WriteResult)
async def upsert_analysts(payload: UpsertRequest) -> dict[str, Any]:
    return await upsert_analysts_service(payload.records)

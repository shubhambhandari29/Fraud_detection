"""PAL Severity claims routes."""

from typing import Any

from fastapi import APIRouter, Depends, Request

from core.models.common import WriteResult
from services.auth_service import get_current_user_from_token
from services.pal_severity.claims_service import get_claims, upsert_claims


router = APIRouter(dependencies=[Depends(get_current_user_from_token)])


@router.get("/")
async def get_pal_severity_claims(request: Request) -> list[dict[str, Any]]:
    return await get_claims(dict(request.query_params))


@router.post("/upsert", response_model=WriteResult)
async def upsert_pal_severity_claim(payload: dict[str, Any]) -> dict[str, Any]:
    return await upsert_claims([payload])

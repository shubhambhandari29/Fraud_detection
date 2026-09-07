"""ABI Litigation claims routes."""

from typing import Any

from fastapi import APIRouter, Depends, Request

from core.models.common import WriteResult
from services.abi_litigation.claims_service import get_claims, upsert_claims
from services.auth_service import get_current_user_from_token


router = APIRouter(dependencies=[Depends(get_current_user_from_token)])


@router.get("/")
async def get_abi_litigation_claims(request: Request) -> list[dict[str, Any]]:
    return await get_claims(dict(request.query_params))


@router.post("/upsert", response_model=WriteResult)
async def upsert_abi_litigation_claim(payload: dict[str, Any]) -> dict[str, Any]:
    return await upsert_claims([payload])

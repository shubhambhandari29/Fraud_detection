"""ABI Litigation claims routes."""

from typing import Any

from fastapi import APIRouter, Depends, Request

from core.models.common import WriteResult
from core.models.auth import LoginResponse
from services.abi_litigation.claims_service import (
    get_claim_by_number,
    get_claims,
    upsert_claims,
)
from services.auth_service import get_current_user_from_token


router = APIRouter(dependencies=[Depends(get_current_user_from_token)])


@router.get("/")
async def get_abi_litigation_claims(request: Request) -> list[dict[str, Any]]:
    return await get_claims(dict(request.query_params))


@router.get("/get/{claim_number}")
async def get_abi_litigation_claim_by_number(
    claim_number: str,
) -> list[dict[str, Any]]:
    return await get_claim_by_number(claim_number)


@router.post("/upsert", response_model=WriteResult)
async def upsert_abi_litigation_claim(
    payload: dict[str, Any],
    current_user: LoginResponse = Depends(get_current_user_from_token),
) -> dict[str, Any]:
    return await upsert_claims([payload], current_user.user.id)

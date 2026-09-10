"""Claims API routes."""

from typing import Any

from fastapi import APIRouter, Depends, Request

from core.models.common import WriteResult
from core.models.auth import LoginResponse
from core.models.third_party_auto import ClaimTransferRequest
from services.auth_service import get_current_user_from_token
from services.third_party_auto.claims_service import get_claims as get_claims_service
from services.third_party_auto.claims_service import transfer_claims as transfer_claims_service
from services.third_party_auto.claims_service import upsert_claims as upsert_claims_service


router = APIRouter(dependencies=[Depends(get_current_user_from_token)])


@router.get("/")
async def get_claims(
    request: Request,
) -> list[dict[str, Any]]:
    return await get_claims_service(dict(request.query_params))


@router.post("/upsert", response_model=WriteResult)
async def upsert_claims(
    payload: dict[str, Any],
    current_user: LoginResponse = Depends(get_current_user_from_token),
) -> dict[str, Any]:
    return await upsert_claims_service([payload], current_user.user.id)


@router.post("/transfer", response_model=WriteResult)
async def transfer_claims(
    payload: ClaimTransferRequest,
    current_user: LoginResponse = Depends(get_current_user_from_token),
) -> dict[str, Any]:
    return await transfer_claims_service(
        payload.target_user,
        payload.claim_numbers,
        current_user.user.id,
    )

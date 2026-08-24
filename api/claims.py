"""Claims API routes."""

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query

from core.models.common import WriteResult
from services.auth_service import get_current_user_from_token
from services.claims_service import get_claims as get_claims_service
from services.claims_service import upsert_claims as upsert_claims_service


router = APIRouter(dependencies=[Depends(get_current_user_from_token)])


@router.get("/")
async def get_claims(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    status: Literal["Pending", "Monitor", "Dismissed", "Blank", "Assigned"] | None = Query(
        default=None, alias="Status"
    ),
    addressed: bool | None = Query(default=None, alias="Addressed"),
) -> list[dict[str, Any]]:
    return await get_claims_service(limit, offset, status, addressed)


@router.post("/upsert", response_model=WriteResult)
async def upsert_claims(payload: dict[str, Any]) -> dict[str, Any]:
    return await upsert_claims_service([payload])

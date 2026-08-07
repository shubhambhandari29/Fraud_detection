"""F5 identity-header passthrough route used by the frontend."""

from fastapi import APIRouter, Header

from core.models.auth import UserInfoResponse


router = APIRouter()


@router.get("/user_info", response_model=UserInfoResponse)
async def user_info(
    username: str | None = Header(default=None),
    groups: str | None = Header(default=None),
) -> UserInfoResponse:
    return UserInfoResponse(user=username or "", groups=groups or "")

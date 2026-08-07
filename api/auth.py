"""Authentication routes."""

from fastapi import APIRouter, Request, Response

from core.models.auth import LoginRequest, LoginResponse
from services.auth_service import get_current_user_from_token, login_user


router = APIRouter()


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest, response: Response) -> LoginResponse:
    return await login_user(payload, response)


@router.get("/me", response_model=LoginResponse)
async def get_current_user(request: Request) -> LoginResponse:
    return await get_current_user_from_token(request)

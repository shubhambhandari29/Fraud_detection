"""Authentication routes."""

from fastapi import APIRouter, Response

from core.models.auth import LoginRequest, LoginResponse
from services.auth_service import login_user


router = APIRouter()


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest, response: Response) -> LoginResponse:
    return await login_user(payload, response)

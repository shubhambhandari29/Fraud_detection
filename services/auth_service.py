"""Temporary, database-free authentication service."""

import hmac
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, Request, Response, status

from core.config import settings
from core.jwt_handler import create_access_token, create_refresh_token, decode_access_token
from core.models.auth import LoginRequest, LoginResponse, UserResponse


TEMPORARY_PASSWORD = "12345678"
AVAILABLE_MODELS = "fraud, litigation, severity"
SESSION_COOKIE_NAME = "session"
REFRESH_COOKIE_NAME = "refresh_session"


def _set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    common_options = {
        "httponly": True,
        "secure": settings.SECURE_COOKIE,
        "samesite": settings.SAME_SITE,
    }
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=access_token,
        max_age=settings.ACCESS_TOKEN_VALIDITY * 60,
        expires=datetime.now(UTC)
        + timedelta(minutes=settings.ACCESS_TOKEN_VALIDITY),
        path="/",
        **common_options,
    )
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        max_age=settings.REFRESH_TOKEN_VALIDITY * 60,
        expires=datetime.now(UTC)
        + timedelta(minutes=settings.REFRESH_TOKEN_VALIDITY),
        path="/auth/refresh",
        **common_options,
    )


def _build_user(email: str, models: str = AVAILABLE_MODELS) -> UserResponse:
    return UserResponse(
        id=email,
        first_name=email.split("@", maxsplit=1)[0],
        last_name="",
        email=email,
        models=models,
        branch=None,
    )


async def login_user(payload: LoginRequest, response: Response) -> LoginResponse:
    """Authenticate against the temporary password and issue JWTs."""
    if not hmac.compare_digest(payload.password, TEMPORARY_PASSWORD):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "Wrong password"},
        )

    email = str(payload.email).strip().lower()
    user = _build_user(email)

    access_token = create_access_token(user.id, user.models)
    refresh_token = create_refresh_token(user.id, user.models)
    _set_auth_cookies(response, access_token, refresh_token)

    return LoginResponse(
        message="Sign in successful",
        user=user,
        token=access_token,
    )


async def get_current_user_from_token(request: Request) -> LoginResponse:
    """Validate SAC's session cookie and return the authenticated user."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "Not authenticated"},
        )

    try:
        payload = decode_access_token(token)
        email = str(payload.get("sub") or "").strip().lower()
        models = str(payload.get("models") or "").strip()
        if not email or not models:
            raise ValueError("JWT is missing a user or models")
        user = _build_user(email, models)
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "Invalid token"},
        ) from error

    return LoginResponse(
        message="User authenticated",
        user=user,
        token=token,
    )

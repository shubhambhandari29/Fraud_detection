"""Temporary, database-free authentication service."""

import hmac
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, Response, status

from core.config import settings
from core.jwt_handler import create_access_token, create_refresh_token
from core.models.auth import LoginRequest, LoginResponse, UserResponse


ADMIN_EMAIL = "ak3gupta@hanover.com"
TEMPORARY_PASSWORD = "12345678"
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


async def login_user(payload: LoginRequest, response: Response) -> LoginResponse:
    """Authenticate against the temporary password and issue JWTs."""
    if not hmac.compare_digest(payload.password, TEMPORARY_PASSWORD):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "Wrong password"},
        )

    email = str(payload.email).strip().lower()
    role = "admin" if email == ADMIN_EMAIL else "user"
    user = UserResponse(
        id=email,
        first_name=email.split("@", maxsplit=1)[0],
        last_name="",
        email=email,
        role=role,
        branch=None,
    )

    access_token = create_access_token(user.id, user.role)
    refresh_token = create_refresh_token(user.id, user.role)
    _set_auth_cookies(response, access_token, refresh_token)

    return LoginResponse(
        message="Sign in successful",
        user=user,
        token=access_token,
    )

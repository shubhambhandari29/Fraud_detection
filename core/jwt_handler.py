"""JWT creation and validation helpers."""

from datetime import UTC, datetime, timedelta

import jwt
from fastapi import HTTPException

from core.config import settings


ALGORITHM = "HS256"


def create_access_token(user_id: str, models: str | None = None) -> str:
    expires_at = datetime.now(UTC) + timedelta(minutes=settings.ACCESS_TOKEN_VALIDITY)
    payload = {"sub": str(user_id), "exp": expires_at, "type": "access"}
    if models is not None:
        payload["models"] = models
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(user_id: str, models: str | None = None) -> str:
    expires_at = datetime.now(UTC) + timedelta(minutes=settings.REFRESH_TOKEN_VALIDITY)
    payload = {"sub": str(user_id), "exp": expires_at, "type": "refresh"}
    if models is not None:
        payload["models"] = models
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(status_code=403, detail="Invalid token")
        return payload
    except jwt.ExpiredSignatureError as error:
        raise HTTPException(status_code=401, detail="Token expired") from error
    except jwt.InvalidTokenError as error:
        raise HTTPException(status_code=403, detail="Invalid token") from error

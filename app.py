"""Fraud FastAPI application assembly."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.auth import router as auth_router
from api.claims import router as claims_router
from api.cts_users import router as cts_users_router
from api.user_info import router as user_info_router
from api.user_roster import router as user_roster_router
from core.config import settings


app = FastAPI(title="Fraud API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["health"])
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(user_info_router, prefix="/api", tags=["auth"])
app.include_router(claims_router, prefix="/claims", tags=["claims"])
app.include_router(cts_users_router, prefix="/cts_users", tags=["cts_users"])
app.include_router(user_roster_router, prefix="/user_roster", tags=["user_roster"])

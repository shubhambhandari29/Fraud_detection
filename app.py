"""Fraud FastAPI application assembly."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from api.auth import router as auth_router
from api.abi_litigation.claims import router as abi_litigation_router
from api.pal_severity.claims import router as pal_severity_router
from api.third_party_auto.claims import router as claims_router
from api.third_party_auto.cts_users import router as cts_users_router
from api.third_party_auto.user_roster import router as user_roster_router
from api.user_info import router as user_info_router
from core.config import settings


app = FastAPI(
    title="Fraud API",
    version="0.1.0",
    swagger_ui_parameters={"syntaxHighlight": False},
)
app.add_middleware(GZipMiddleware, minimum_size=500, compresslevel=6)
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
app.include_router(
    abi_litigation_router,
    prefix="/abi_litigation",
    tags=["abi_litigation"],
)
app.include_router(
    pal_severity_router,
    prefix="/pal_severity",
    tags=["pal_severity"],
)

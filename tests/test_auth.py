import asyncio

import pytest
from fastapi import HTTPException, Response
from fastapi.testclient import TestClient
from core.jwt_handler import decode_access_token
from core.models.auth import LoginRequest
from app import app
from services.auth_service import login_user


def login(email: str, password: str = "12345678"):
    response = Response()
    result = asyncio.run(
        login_user(LoginRequest(email=email, password=password), response)
    )
    return result, response


def test_login_returns_models_in_response_and_token():
    result, response = login("AK3GUPTA@HANOVER.COM")

    assert result.message == "Sign in successful"
    assert result.user.email == "ak3gupta@hanover.com"
    assert result.user.models == "fraud, litigation, severity, subrogation"
    assert result.token
    assert "session=" in response.headers["set-cookie"]

    claims = decode_access_token(result.token)
    assert claims["sub"] == "ak3gupta@hanover.com"
    assert claims["models"] == "fraud, litigation, severity, subrogation"
    assert claims["type"] == "access"


def test_models_are_currently_the_same_for_every_user():
    result, _ = login("analyst@hanover.com")

    assert result.user.models == "fraud, litigation, severity, subrogation"
    assert decode_access_token(result.token)["models"] == (
        "fraud, litigation, severity, subrogation"
    )


def test_wrong_password_is_rejected():
    with pytest.raises(HTTPException) as error:
        login("analyst@hanover.com", "wrong-password")

    assert error.value.status_code == 401
    assert error.value.detail == {"error": "Wrong password"}


def test_me_returns_authenticated_user_from_session_cookie():
    client = TestClient(app)
    login_response = client.post(
        "/auth/login",
        json={"email": "analyst@hanover.com", "password": "12345678"},
    )

    response = client.get("/auth/me")

    assert login_response.status_code == 200
    assert response.status_code == 200
    assert response.json()["message"] == "User authenticated"
    assert response.json()["user"]["email"] == "analyst@hanover.com"
    assert response.json()["user"]["models"] == (
        "fraud, litigation, severity, subrogation"
    )
    assert response.json()["token"] == login_response.json()["token"]


def test_me_rejects_request_without_session_cookie():
    response = TestClient(app).get("/auth/me")

    assert response.status_code == 401
    assert response.json()["detail"] == {"error": "Not authenticated"}


def test_user_info_returns_f5_headers():
    response = TestClient(app).get(
        "/api/user_info",
        headers={"username": "AK3GUPTA", "groups": "admin,user"},
    )

    assert response.status_code == 200
    assert response.json() == {"user": "AK3GUPTA", "groups": "admin,user"}

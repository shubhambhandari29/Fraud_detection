"""Claim-specific GET endpoint coverage for all selector tables."""

import asyncio
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from api.abi_litigation import claims as litigation_api
from api.auto_subrogation import claims as subrogation_api
from api.pal_severity import claims as severity_api
from api.third_party_auto import claims as fraud_api
from app import app
from services.auth_service import get_current_user_from_token
from services.abi_litigation import claims_service as litigation
from services.auto_subrogation import claims_service as subrogation
from services.pal_severity import claims_service as severity
from services.third_party_auto import claims_service as fraud


@pytest.mark.parametrize(
    ("service", "table", "claim_column", "claim_number"),
    [
        (
            fraud,
            "dbo.tblFraudThirdPartyAutoBIEDW_OpenClaims_Predictions_Selector",
            "CLM_NBR",
            "85-00837106",
        ),
        (
            litigation,
            "dbo.tblALLitigation_OpenClaimsPredictions_Selector",
            "DERIVE_CLM_FTR_NBR",
            "85-00837106-02",
        ),
        (
            severity,
            "dbo.tblPALSeverity_OpenClaimsPredictions_Selector_GAME",
            "CLM_NBR",
            "85-00560726",
        ),
        (
            subrogation,
            "dbo.tblAutoSubro_combinedOpenClaimsPredictions_Selector",
            "CLM_NBR_U",
            "85-00837106",
        ),
    ],
)
def test_claim_get_uses_native_claim_column_and_returns_every_matching_row(
    monkeypatch, service, table, claim_column, claim_number
):
    received = {}

    async def fake_fetch_records_async(received_table, **kwargs):
        received.update(table=received_table, **kwargs)
        return [
            {"ID": 1, claim_column: claim_number, "Date Generated": datetime(2026, 9, 1)},
            {"ID": 2, claim_column: claim_number, "Date Generated": None},
        ]

    monkeypatch.setattr(service, "fetch_records_async", fake_fetch_records_async)

    result = asyncio.run(service.get_claim_by_number(claim_number))

    assert received == {
        "table": table,
        "filters": {claim_column: claim_number},
        "validate_filters": True,
    }
    assert result == [
        {"ID": 1, claim_column: claim_number, "Date Generated": "2026-09-01"},
        {"ID": 2, claim_column: claim_number, "Date Generated": None},
    ]


def test_claim_get_routes_are_registered():
    paths = {route.path for route in app.routes}
    assert {
        "/claims/get/{claim_number}",
        "/abi_litigation/get/{claim_number}",
        "/pal_severity/get/{claim_number}",
        "/auto_subrogation/get/{claim_number}",
    } <= paths


@pytest.mark.parametrize(
    ("api_module", "service_name", "path", "claim_number"),
    [
        (fraud_api, "get_claim_by_number_service", "/claims/get/85-00837106", "85-00837106"),
        (
            litigation_api,
            "get_claim_by_number",
            "/abi_litigation/get/85-00837106-02",
            "85-00837106-02",
        ),
        (
            severity_api,
            "get_claim_by_number",
            "/pal_severity/get/85-00560726",
            "85-00560726",
        ),
        (
            subrogation_api,
            "get_claim_by_number",
            "/auto_subrogation/get/85-00837106",
            "85-00837106",
        ),
    ],
)
def test_claim_get_routes_forward_path_value(
    monkeypatch, api_module, service_name, path, claim_number
):
    received = []

    async def fake_service(value):
        received.append(value)
        return [{"claim": value}]

    monkeypatch.setattr(api_module, service_name, fake_service)
    app.dependency_overrides[get_current_user_from_token] = lambda: object()
    try:
        response = TestClient(app).get(path)
    finally:
        app.dependency_overrides.pop(get_current_user_from_token, None)

    assert response.status_code == 200
    assert response.json() == [{"claim": claim_number}]
    assert received == [claim_number]

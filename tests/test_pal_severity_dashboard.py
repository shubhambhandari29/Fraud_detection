"""PAL Severity dashboard behavior and route coverage."""

import asyncio
from datetime import datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient

from api.pal_severity import dashboard as dashboard_api
from app import app
import db
from services.auth_service import get_current_user_from_token
from services.pal_severity import dashboard_service


def test_dashboard_returns_all_matching_rows_and_carpe_indicator(monkeypatch):
    monkeypatch.setattr(
        dashboard_service,
        "_fetch_edw",
        lambda claim: [
            {"DERIVE_CLM_FTR_NBR": claim, "FTR_CREAT_DT_U": datetime(2026, 10, 13)},
            {"DERIVE_CLM_FTR_NBR": claim, "FTR_CREAT_DT_U": "10/14/2026"},
        ],
    )
    monkeypatch.setattr(
        dashboard_service,
        "_fetch_carpe",
        lambda claim: [{"ClientID": claim, "ReasonCode": "R1"}],
    )

    result = asyncio.run(dashboard_service.get_dashboard(" 85-00837106-02 "))

    assert result.claim_number == "85-00837106-02"
    assert result.carpe_available == "Y"
    assert len(result.edw) == 2
    assert result.edw[0]["FTR_CREAT_DT_U"] == "2026-10-13"
    assert result.edw[1]["FTR_CREAT_DT_U"] == "2026-10-14"
    assert result.carpe == [{"ClientID": "85-00837106-02", "ReasonCode": "R1"}]


def test_dashboard_route_requires_auth_and_forwards_claim(monkeypatch):
    async def fake_dashboard(claim_number):
        return {"claim_number": claim_number, "carpe_available": "N"}

    monkeypatch.setattr(dashboard_api, "get_dashboard", fake_dashboard)
    client = TestClient(app)
    assert client.get("/pal_severity/dashboard/85-00837106-02").status_code == 401

    app.dependency_overrides[get_current_user_from_token] = lambda: object()
    try:
        response = client.get("/pal_severity/dashboard/85-00837106-02")
    finally:
        app.dependency_overrides.pop(get_current_user_from_token, None)

    assert response.status_code == 200
    assert response.json() == {
        "claim_number": "85-00837106-02",
        "carpe_available": "N",
        "edw": [],
        "carpe": [],
    }


def test_vendor_connection_can_use_separate_server(monkeypatch):
    monkeypatch.setattr(
        db,
        "settings",
        SimpleNamespace(
            DB_DRIVER="{Driver}",
            DB_SERVER="default-server",
            DB_NAME="CLMDS_DataModelingAndTextMining",
            DB_AUTH="auth",
        ),
    )

    connection_string = db._build_connection_string("CLM_VendorData", "vendor-server")

    assert "Server=vendor-server;" in connection_string
    assert "Database=CLM_VendorData;" in connection_string

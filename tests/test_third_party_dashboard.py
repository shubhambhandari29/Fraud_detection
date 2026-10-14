"""Third Party Auto dashboard API and aggregation coverage."""

import asyncio
from datetime import datetime

from fastapi.testclient import TestClient

from api.third_party_auto import dashboard as dashboard_api
from app import app
from services.auth_service import get_current_user_from_token
from services.third_party_auto import dashboard_service


def test_dashboard_aggregates_sections_and_power_bi_indicators(monkeypatch):
    def fake_fraud(claim_number):
        assert claim_number == "85-00370154"
        return {
            "edw": [
                {
                    "Clm_Nbr": claim_number,
                    "FTR_CREAT_DT_U": datetime(2026, 10, 7, 12, 30),
                    "ISO_match_found": "Y",
                }
            ],
            "cts": [
                {
                    "ReferralStatus": "Investigator Assigned",
                    "ResultStatus": "Denied",
                }
            ],
            "smart_features": [{"AutoScoreID": 1}],
            "watchlist": [{"ID": 407}],
            "ies_bills": [
                {
                    "Demand Package Number": "D1",
                    "Bill ID": "B1",
                    "Bill Line": 1,
                }
            ],
            "ies_flags": [
                {
                    "Demand Package Number": "D1",
                    "Bill ID": "B1",
                    "Bill Line": 1,
                    "Flag Short Name": "Duplicate",
                    "Flag Type Code": "DUP",
                    "Procedure Category": "Medical",
                    "Procedure Sub Category": "Imaging",
                },
                {
                    "Demand Package Number": "D1",
                    "Bill ID": "B1",
                    "Bill Line": 1,
                    "Flag Short Name": "Duplicate",
                    "Flag Type Code": "DUP",
                    "Procedure Category": "Medical",
                    "Procedure Sub Category": "Imaging",
                },
            ],
            "alert_reason_rows": [
                {"alert_reason_concat": "Reason A;Reason B;"},
                {"alert_reason_concat": "Reason A"},
            ],
        }

    monkeypatch.setattr(dashboard_service, "_fetch_fraud_sections", fake_fraud)
    monkeypatch.setattr(
        dashboard_service,
        "_fetch_vendor_sections",
        lambda claim_number: {"carpe": [{"ClientID": claim_number + "-01"}]},
    )
    monkeypatch.setattr(
        dashboard_service,
        "_fetch_datatext_sections",
        lambda claim_number: {"game_summary": [{"clm_nbr": claim_number, "topic": "Summary"}]},
    )

    result = asyncio.run(dashboard_service.get_dashboard(" 85-00370154 "))

    assert result.claim_number == "85-00370154"
    assert result.indicators.model_dump() == {
        "assigned": "Y",
        "dcw": "Y",
        "cts": "Y",
        "smart_features": "Y",
        "watchlist": "Y",
        "carpe": "Y",
        "ies_bills": "Y",
        "iso_match": "Y",
    }
    assert result.edw[0]["FTR_CREAT_DT_U"] == "2026-10-07"
    assert result.alert_reasons == ["Reason A", "Reason B"]
    assert result.ies_bills[0]["Flag Short Names"] == "Duplicate"
    assert result.ies_bills[0]["Flag Type Codes"] == "DUP"
    assert len(result.ies_bills[0]["Flags"]) == 2


def test_dashboard_returns_n_for_missing_related_sections(monkeypatch):
    monkeypatch.setattr(
        dashboard_service,
        "_fetch_fraud_sections",
        lambda claim_number: {
            "edw": [],
            "cts": [],
            "smart_features": [],
            "watchlist": [],
            "ies_bills": [],
            "ies_flags": [],
            "alert_reason_rows": [],
        },
    )
    monkeypatch.setattr(
        dashboard_service,
        "_fetch_vendor_sections",
        lambda claim_number: {"carpe": []},
    )
    monkeypatch.setattr(
        dashboard_service,
        "_fetch_datatext_sections",
        lambda claim_number: {"game_summary": []},
    )

    result = asyncio.run(dashboard_service.get_dashboard("85-00370154"))

    assert set(result.indicators.model_dump().values()) == {"N"}


def test_dashboard_route_is_authenticated_and_forwards_claim(monkeypatch):
    received = []

    async def fake_dashboard(claim_number):
        received.append(claim_number)
        return {
            "claim_number": claim_number,
            "indicators": {
                "assigned": "N",
                "dcw": "N",
                "cts": "N",
                "smart_features": "N",
                "watchlist": "N",
                "carpe": "N",
                "ies_bills": "N",
                "iso_match": "N",
            },
        }

    monkeypatch.setattr(dashboard_api, "get_dashboard", fake_dashboard)
    app.dependency_overrides[get_current_user_from_token] = lambda: object()
    try:
        response = TestClient(app).get("/fraud/dashboard/85-00370154")
    finally:
        app.dependency_overrides.pop(get_current_user_from_token, None)

    assert response.status_code == 200
    assert response.json()["claim_number"] == "85-00370154"
    assert received == ["85-00370154"]


def test_dashboard_route_is_registered():
    assert "/fraud/dashboard/{claim_number}" in {route.path for route in app.routes}

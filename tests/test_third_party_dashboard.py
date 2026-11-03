"""Third Party Auto dashboard API and aggregation coverage."""

import asyncio
from contextlib import contextmanager
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
        lambda claim_number: {
            "game_summary": [{"clm_nbr": claim_number, "topic": "Summary"}],
            "status_feedback": [
                {"ID": "1111", "Status": "Assigned", "Feedback": "Investigate",
                 "Feedback Notes": "First"},
                {"ID": "2222", "Status": "Dismissed", "Feedback": "No concerns",
                 "Feedback Notes": "Second"},
            ],
        },
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
    assert result.status_feedback == [
        {"ID": "1111", "Status": "Assigned", "Feedback": "Investigate",
         "Feedback Notes": "First"},
        {"ID": "2222", "Status": "Dismissed", "Feedback": "No concerns",
         "Feedback Notes": "Second"},
    ]
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
        lambda claim_number: {"game_summary": [], "status_feedback": []},
    )

    result = asyncio.run(dashboard_service.get_dashboard("85-00370154"))

    assert set(result.indicators.model_dump().values()) == {"N"}
    assert result.status_feedback == []
    assert result.edw[0]["Clm_Nbr"] == "85-00370154"
    assert result.edw[0]["_dummy"] is True
    assert result.watchlist[0]["_dummy"] is True
    assert result.ies_bills[0]["Claim Number"] == "85-00370154"
    assert result.ies_bills[0]["Flags"][0]["_dummy"] is True


def test_dashboard_placeholder_switch_can_restore_empty_arrays(monkeypatch):
    monkeypatch.setattr(dashboard_service.settings, "DASHBOARD_PLACEHOLDERS_ENABLED", False)
    monkeypatch.setattr(
        dashboard_service,
        "_fetch_fraud_sections",
        lambda claim_number: {
            "edw": [], "cts": [], "smart_features": [], "watchlist": [],
            "ies_bills": [], "ies_flags": [], "alert_reason_rows": [],
        },
    )
    monkeypatch.setattr(
        dashboard_service, "_fetch_vendor_sections", lambda claim_number: {"carpe": []}
    )
    monkeypatch.setattr(
        dashboard_service,
        "_fetch_datatext_sections",
        lambda claim_number: {"game_summary": [], "status_feedback": []},
    )

    result = asyncio.run(dashboard_service.get_dashboard("85-00370154"))

    assert result.edw == []
    assert result.watchlist == []
    assert result.ies_bills == []
    assert result.status_feedback == []


def test_status_feedback_query_uses_datatext_database_and_parameterized_claim(monkeypatch):
    calls = []

    class Cursor:
        def execute(self, query, params):
            calls.append((query, params))
            self.description = (
                [("ID",), ("Status",), ("Feedback",), ("Feedback Notes",)]
                if query == dashboard_service.STATUS_FEEDBACK_QUERY
                else [("clm_nbr",), ("topic",), ("value",), ("template",)]
            )

        def fetchall(self):
            return (
                [("1111", "Assigned", "Investigate", "Review note"),
                 ("2222", "Dismissed", "No concerns", None)]
                if self.description[0][0] == "ID"
                else []
            )

    class Connection:
        def cursor(self):
            return Cursor()

    @contextmanager
    def connect(database_name):
        assert database_name == dashboard_service.settings.DATATEXT_DB_NAME
        yield Connection()

    monkeypatch.setattr(dashboard_service, "db_connection", connect)

    sections = dashboard_service._fetch_datatext_sections("85-00370154")

    assert sections["status_feedback"] == [
        {"ID": "1111", "Status": "Assigned", "Feedback": "Investigate",
         "Feedback Notes": "Review note"},
        {"ID": "2222", "Status": "Dismissed", "Feedback": "No concerns",
         "Feedback Notes": None},
    ]
    assert calls == [
        (dashboard_service.GAME_SUMMARY_QUERY, ["85-00370154"]),
        (dashboard_service.STATUS_FEEDBACK_QUERY, ["85-00370154"]),
    ]


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

"""ABI Litigation dashboard API and aggregation coverage."""

import asyncio
from datetime import datetime

from fastapi.testclient import TestClient

from api.abi_litigation import dashboard as dashboard_api
from app import app
from services.abi_litigation import dashboard_service
from services.auth_service import get_current_user_from_token


def test_dashboard_returns_edw_and_parsed_game_rows(monkeypatch):
    monkeypatch.setattr(
        dashboard_service,
        "_fetch_dashboard_sections",
        lambda claim_number: {
            "edw": [
                {
                    "Claim Feature Number": claim_number,
                    "Litigation Status": "Open",
                }
            ],
            "game_rows": [
                {
                    "DERIVE_CLM_FTR_NBR": claim_number,
                    "Topic": "Case Litigation & Claims",
                    "Summary": (
                        "## Summary of the Current Status of the Claim: Claim remains open.\n"
                        "## Current Status of the Litigation: **Discovery**\n"
                        "## Next Steps in the Litigation Process: Schedule deposition.\n"
                        "## Key People Involved: Jane Smith\n"
                        "## Information Not Available: Trial date\n"
                        "## Case Investigation: Investigation continues."
                    ),
                    "Game_Run_Date": datetime(2026, 10, 13, 14, 30),
                    "Word_Length": 42,
                },
                {
                    "DERIVE_CLM_FTR_NBR": claim_number,
                    "Topic": "Case Litigation & Claims",
                    "Summary": "Error : 400",
                    "Game_Run_Date": datetime(2026, 10, 12),
                    "Word_Length": 3,
                },
            ],
        },
    )

    result = asyncio.run(dashboard_service.get_dashboard(" 85-00837106-02 "))

    assert result.claim_number == "85-00837106-02"
    assert result.edw == [
        {
            "Claim Feature Number": "85-00837106-02",
            "Litigation Status": "Open",
        }
    ]
    assert result.game_summary == [
        {
            "DERIVE_CLM_FTR_NBR": "85-00837106-02",
            "Game_Run_Date": "2026-10-13",
            "Word_Length": 42,
            "Summary of the Current Status of the Claim": "Claim remains open.",
            "Current Status of the Litigation": "Discovery",
            "Next Steps in the Litigation Process": "Schedule deposition.",
            "Key People Involved": "Jane Smith",
            "Information Not Available": "Trial date",
            "Case Investigation": "Investigation continues.",
        }
    ]


def test_dashboard_preserves_multiple_game_runs(monkeypatch):
    monkeypatch.setattr(
        dashboard_service,
        "_fetch_dashboard_sections",
        lambda claim_number: {
            "edw": [],
            "game_rows": [
                {
                    "DERIVE_CLM_FTR_NBR": claim_number,
                    "Summary": f"## Current Status of the Litigation: Run {run_number}",
                    "Game_Run_Date": datetime(2026, 10, run_number),
                    "Word_Length": run_number,
                }
                for run_number in (2, 1)
            ],
        },
    )

    result = asyncio.run(dashboard_service.get_dashboard("85-00837106-02"))

    assert len(result.game_summary) == 2
    assert [row["Current Status of the Litigation"] for row in result.game_summary] == [
        "Run 2",
        "Run 1",
    ]


def test_dashboard_returns_legacy_game_sections(monkeypatch):
    monkeypatch.setattr(
        dashboard_service,
        "_fetch_dashboard_sections",
        lambda claim_number: {
            "edw": [],
            "game_rows": [],
            "legacy_game_rows": [
                {
                    "DERIVE_CLM_FTR_NBR": claim_number,
                    "Topic": "Status",
                    "Summary": "**In discovery**",
                    "Game_Run_Date": datetime(2026, 10, 12),
                    "Word_Length": 2,
                }
            ],
        },
    )

    result = asyncio.run(dashboard_service.get_dashboard("85-00837106-02"))

    assert result.game_summary_legacy[0]["Claim Summary"] == "In discovery"
    assert result.game_summary_legacy[0]["Game_Run_Date"] == "2026-10-12"


def test_dashboard_route_is_authenticated_and_forwards_claim(monkeypatch):
    received = []

    async def fake_dashboard(claim_number):
        received.append(claim_number)
        return {"claim_number": claim_number, "edw": [], "game_summary": []}

    monkeypatch.setattr(dashboard_api, "get_dashboard", fake_dashboard)
    app.dependency_overrides[get_current_user_from_token] = lambda: object()
    try:
        response = TestClient(app).get(
            "/abi_litigation/dashboard/85-00837106-02"
        )
    finally:
        app.dependency_overrides.pop(get_current_user_from_token, None)

    assert response.status_code == 200
    assert response.json()["claim_number"] == "85-00837106-02"
    assert received == ["85-00837106-02"]


def test_dashboard_route_is_registered():
    assert "/abi_litigation/dashboard/{claim_number}" in {
        route.path for route in app.routes
    }

"""Law Firm Profiling aggregation and API behavior."""

import asyncio
from datetime import datetime

from fastapi.testclient import TestClient

from api.abi_litigation import law_firm_dashboard as law_firm_api
from app import app
from services.abi_litigation import law_firm_dashboard_service
from services.auth_service import get_current_user_from_token


def test_law_firm_kpis_deduplicate_matter_ids(monkeypatch):
    rows = [
        {
            "CLM_NBR_U": "85-00000001",
            "MATTER_HCS_SYS_ID": "M1",
            "ATTY_ACTVTY_RESLTN_DESC": "Settled - Mediation",
            "LAWSUIT_FINL_STTLMT_AMT": 2000,
            "LGL_MATTER_OPEN_DT": datetime(2026, 1, 1),
            "LAWSUIT_CLOSE_DT": datetime(2026, 1, 11),
            "CLM_RPTD_DT_U": datetime(2025, 1, 1),
            "CLM_CLOSE_DT_U": datetime(2025, 1, 21),
            "HCS_POL_LOB_DESC": "Auto",
            "CLM_JRSDTN_ST_ABBR": "NY",
        },
        {
            "CLM_NBR_U": "85-00000001",
            "MATTER_HCS_SYS_ID": "M1",
            "ATTY_ACTVTY_RESLTN_DESC": "Settled - Mediation",
            "LAWSUIT_FINL_STTLMT_AMT": 2000,
            "LGL_MATTER_OPEN_DT": datetime(2026, 1, 1),
            "LAWSUIT_CLOSE_DT": datetime(2026, 1, 11),
            "CLM_RPTD_DT_U": datetime(2025, 1, 1),
            "CLM_CLOSE_DT_U": datetime(2025, 1, 21),
            "HCS_POL_LOB_DESC": "Auto",
            "CLM_JRSDTN_ST_ABBR": "NY",
        },
        {
            "CLM_NBR_U": "85-00000002",
            "MATTER_HCS_SYS_ID": "M2",
            "ATTY_ACTVTY_RESLTN_DESC": "Trial - Verdict for Plaintiff",
            "LAWSUIT_FINL_STTLMT_AMT": None,
            "LGL_MATTER_OPEN_DT": datetime(2026, 2, 1),
            "LAWSUIT_CLOSE_DT": None,
            "CLM_RPTD_DT_U": datetime(2025, 2, 1),
            "CLM_CLOSE_DT_U": None,
            "HCS_POL_LOB_DESC": "Auto",
            "CLM_JRSDTN_ST_ABBR": "NJ",
        },
    ]
    monkeypatch.setattr(
        law_firm_dashboard_service,
        "_fetch_law_firm_sections",
        lambda name: {"claim_info": rows, "notes": [{"Category": "Full Summary", "Note_Chunk": name}]},
    )

    result = asyncio.run(law_firm_dashboard_service.get_law_firm_dashboard("  Firm A  "))

    assert result.law_firm_name == "Firm A"
    assert result.kpis.claim_count == 2
    assert result.kpis.legal_matter_count == 2
    assert result.kpis.legal_matter_open_count == 1
    assert result.kpis.settlement_percentage == 50
    assert result.kpis.trial_percentage == 50
    assert result.kpis.litigation_duration_days == 10
    assert result.kpis.claim_duration_days == 20
    assert result.notes == [{"Category": "Full Summary", "Note_Chunk": "Firm A"}]
    assert {row["value"]: row["count"] for row in result.settlement_bins}["$1K-$10K"] == 1
    assert result.line_of_business_counts == [{"value": "Auto", "count": 2}]


def test_law_firm_route_requires_auth(monkeypatch):
    async def fake_dashboard(name):
        return {
            "law_firm_name": name,
            "kpis": {
                "claim_count": 0,
                "legal_matter_count": 0,
                "legal_matter_open_count": 0,
                "settlement_percentage": 0,
                "trial_percentage": 0,
                "litigation_open_percentage": 0,
                "litigation_duration_days": None,
                "claim_duration_days": None,
            },
        }

    monkeypatch.setattr(law_firm_api, "get_law_firm_dashboard", fake_dashboard)
    client = TestClient(app)
    assert client.get("/abi_litigation/law_firm/dashboard/Firm%20A").status_code == 401

    app.dependency_overrides[get_current_user_from_token] = lambda: object()
    try:
        response = client.get("/abi_litigation/law_firm/dashboard/Firm%20A")
    finally:
        app.dependency_overrides.pop(get_current_user_from_token, None)

    assert response.status_code == 200
    assert response.json()["law_firm_name"] == "Firm A"

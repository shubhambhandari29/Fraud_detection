"""Landing response and selected-row normalization regression coverage."""

import logging
import re
import sqlite3
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from app import app
from services.auth_service import get_current_user_from_token
from services.landing import claims_service as service


@pytest.fixture
def sql_source():
    """Exercise the normalization CTE locally using equivalent SQL functions.

    SQL Server execution and performance still require a live integration check.
    """
    connection = sqlite3.connect(":memory:")
    connection.create_function("LEN", 1, lambda s: len(s) if s is not None else None)
    connection.create_function("REVERSE", 1, lambda s: s[::-1] if s is not None else None)
    connection.create_function(
        "CHARINDEX", 2,
        lambda needle, s: s.find(needle) + 1 if s is not None else None,
    )
    tables = [
        ("tblFraudThirdPartyAutoBIEDW_OpenClaims_Predictions_Selector",
         "CLM_NBR", "ML_PREDICTIONS", "Status", "Feedback"),
        ("tblALLitigation_OpenClaimsPredictions_Selector",
         "DERIVE_CLM_FTR_NBR", "PREDICTIONS", "Action", "ACTION_DETAILS"),
        ("tblPALSeverity_OpenClaimsPredictions_Selector_GAME",
         "CLM_NBR", "PREDICTIONS", "Action", "ACTION_DETAILS"),
        ("tblAutoSubro_combinedOpenClaimsPredictions_Selector",
         "CLM_NBR_U", "PREDICTIONS", "Status", "unused_details"),
    ]
    for table, claim, prediction, action, details in tables:
        connection.execute(
            f'CREATE TABLE [{table}] ([{claim}] TEXT, [{prediction}] TEXT, '
            f'[{action}] TEXT, [{details}] TEXT, [Selected] INTEGER)'
        )

    def run(rows_by_model):
        for model, rows in rows_by_model.items():
            table = tables[service.MODELS.index(model)][0]
            connection.executemany(f"INSERT INTO [{table}] VALUES (?, ?, ?, ?, ?)", rows)
        query = service.LANDING_QUERY.replace("[dbo].", "")
        query = re.sub(r"nvarchar\((?:max|450)\)", "TEXT", query)
        query = re.sub(r"\bN'", "'", query)
        query = query.replace("action_text + ' — ' + details_text",
                              "action_text || ' — ' || details_text")
        return connection.execute(
            query,
            [1, 1, 1, 1],
        ).fetchall()

    yield run
    connection.close()


def test_sql_preserves_duplicates_and_normalizes_all_four_models(sql_source):
    rows = sql_source({
        "fraud": [
            ("85-00837106", "1: High", "Status", "Feedback", 1),
            ("85-00837106", "0: Low", "Excluded", None, 0),
        ],
        "litigation": [
            ("85-00837106-01", "1 : High", "Action A", "Details A", 1),
            ("85-00837106-02", "0 : Low", "Action B", None, 1),
            ("85-00837106-02", "0 : Low", "Action B", None, 1),
        ],
        "severity": [
            ("85-00837106", "1: High", "Settle", None, 1),
            ("85-00837106", "0: Low", None, "Medical Report", 1),
        ],
        "subrogation": [("85-00837106", "1: High", "Assigned", None, 1)],
    })
    assert len(rows) == 7
    assert {row[1] for row in rows} == {"85-00837106"}
    assert rows.count(("litigation", "85-00837106", "Low", "Action B")) == 2
    assert ("fraud", "85-00837106", "High", "Status — Feedback") in rows
    assert ("litigation", "85-00837106", "High", "Action A — Details A") in rows
    assert ("severity", "85-00837106", "Low", "Medical Report") in rows
    assert ("subrogation", "85-00837106", "High", "Assigned") in rows


@pytest.mark.parametrize("prediction", [None, "", "NULL", "unexpected"])
def test_sql_missing_predictions_actions_and_whitespace(sql_source, prediction):
    assert sql_source({"litigation": [
        (" 85-00837106-01 ", prediction, " ", "NULL", 1)
    ]}) == [("litigation", "85-00837106", None, None)]


def test_sql_keeps_claim_number_without_feature_suffix(sql_source):
    assert sql_source({"litigation": [
        ("85-00837106", "  high  ", None, " Detail only ", 1)
    ]}) == [("litigation", "85-00837106", "High", "Detail only")]


@pytest.fixture
def authenticated_client():
    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_current_user_from_token] = lambda: object()
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    app.dependency_overrides.update(previous)


def mock_connection(monkeypatch, sql_rows):
    class Cursor:
        def execute(self, query, params):
            assert params == [1, 1, 1, 1]
            assert query == service.LANDING_QUERY
            assert query.count("UNION ALL") == 3
            assert "OUTER APPLY" not in query
            assert "FOR JSON" not in query

        def fetchall(self):
            return sql_rows

    class Connection:
        def cursor(self):
            return Cursor()

    @contextmanager
    def connect():
        yield Connection()

    monkeypatch.setattr(service, "db_connection", connect)


def test_api_preserves_arrays_nulls_duplicates_and_json_escaping(
    monkeypatch, authenticated_client
):
    recommendations = [
        {"Predictions": "High", "Action": 'Review "medical"\nreport — café'},
        {"Predictions": "Low", "Action": None},
        {"Predictions": "Low", "Action": None},
    ]
    mock_connection(monkeypatch, [
        *(('litigation', '85-00837106', r['Predictions'], r['Action'])
          for r in recommendations),
        ("fraud", "85-00937608", None, None),
    ])
    response = authenticated_client.get("/landing/")
    assert response.status_code == 200
    assert response.json() == [
        {"claim_number": "85-00837106", "fraud": [], "litigation": recommendations,
         "severity": [], "subrogation": []},
        {"claim_number": "85-00937608", "fraud": [{"Predictions": None, "Action": None}],
         "litigation": [], "severity": [], "subrogation": []},
    ]


def test_api_returns_empty_list(monkeypatch, authenticated_client):
    mock_connection(monkeypatch, [])
    response = authenticated_client.get("/landing/")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize("present_model", service.MODELS)
def test_api_missing_models_are_empty_but_null_fields_are_preserved(
    monkeypatch, authenticated_client, present_model
):
    records = [{"Predictions": None, "Action": None}]
    mock_connection(monkeypatch, [(present_model, "85-00837106", None, None)])

    response = authenticated_client.get("/landing/")

    assert response.status_code == 200
    assert response.json() == [{
        "claim_number": "85-00837106",
        **{model: records if model == present_model else [] for model in service.MODELS},
    }]


def test_api_invalid_prediction_is_not_silently_dropped(
    monkeypatch, authenticated_client
):
    mock_connection(monkeypatch, [("fraud", "85-00837106", "invalid", None)])
    response = authenticated_client.get("/landing/")
    assert response.status_code == 500
    assert response.json() == {"detail": {"error": "Database operation failed"}}


def test_grouping_keeps_model_records_separate_and_preserves_duplicates(sql_source):
    rows = sql_source({
        "fraud": [("85-00837106", "1: High", "Status", "Feedback", 1)],
        "litigation": [
            ("85-00837106-01", "1 : High", "Action A", "Details A", 1),
            ("85-00837106-02", "0 : Low", "Action B", None, 1),
            ("85-00837106-02", "0 : Low", "Action B", None, 1),
        ],
        "severity": [
            ("85-00837106", "1: High", "Settle", None, 1),
            ("85-00837106", "0: Low", None, None, 1),
        ],
        "subrogation": [
            ("85-00837106", "1: High", "Assigned", None, 1),
            ("85-00999999", "0: Low", None, None, 1),
        ],
    })
    actual = [claim.model_dump() for claim in service.group_landing_rows(rows)]
    assert actual == [
        {
            "claim_number": "85-00837106",
            "fraud": [{"Predictions": "High", "Action": "Status — Feedback"}],
            "litigation": [
                {"Predictions": "High", "Action": "Action A — Details A"},
                {"Predictions": "Low", "Action": "Action B"},
                {"Predictions": "Low", "Action": "Action B"},
            ],
            "severity": [
                {"Predictions": "High", "Action": "Settle"},
                {"Predictions": "Low", "Action": None},
            ],
            "subrogation": [{"Predictions": "High", "Action": "Assigned"}],
        },
        {
            "claim_number": "85-00999999",
            "fraud": [], "litigation": [], "severity": [],
            "subrogation": [{"Predictions": "Low", "Action": None}],
        },
    ]


def test_service_logs_phase_timings(monkeypatch, caplog):
    mock_connection(monkeypatch, [("fraud", "85-00837106", "High", None)])
    ticks = iter([0, 1, 3, 6, 7, 9])
    monkeypatch.setattr(service, "perf_counter", lambda: next(ticks))
    with caplog.at_level(logging.WARNING, logger=service.__name__):
        service.fetch_landing_claims()
    assert "connection=1.000s execute=2.000s fetch=3.000s" in caplog.text
    assert "close=1.000s grouping_validation=2.000s total=9.000s" in caplog.text
    assert "rows=1 claims=1" in caplog.text


def test_api_requires_authentication():
    assert TestClient(app).get("/landing/").status_code == 401


def test_api_database_failure_is_sanitized(monkeypatch, authenticated_client):
    def fail():
        raise RuntimeError("private connection details")

    monkeypatch.setattr(service, "fetch_landing_claims", fail)
    response = authenticated_client.get("/landing/")
    assert response.status_code == 500
    assert response.json() == {"detail": {"error": "Database operation failed"}}

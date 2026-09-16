"""Landing response and selected-row normalization regression coverage."""

import json
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

    SQL Server's APPLY/FOR JSON portion still requires a live integration check.
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
        query = service.NORMALIZED_ROWS_CTE.replace("[dbo].", "")
        query = re.sub(r"nvarchar\((?:max|450)\)", "TEXT", query)
        query = re.sub(r"\bN'", "'", query)
        query = query.replace("action_text + ' — ' + details_text",
                              "action_text || ' — ' || details_text")
        return connection.execute(
            query + " SELECT model, claim_number, Predictions, Action FROM normalized_rows",
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
            assert query.count("OUTER APPLY") == 4
            assert query.count("FOR JSON PATH, INCLUDE_NULL_VALUES") == 4

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
        ("85-00837106", "[]", json.dumps(recommendations), "[]", "[]"),
        ("85-00937608", '[{"Predictions":null,"Action":null}]', "[]", "[]", "[]"),
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
def test_api_sql_null_arrays_are_empty_but_null_fields_are_preserved(
    monkeypatch, authenticated_client, present_model
):
    records = [{"Predictions": None, "Action": None}]
    columns = [
        json.dumps(records) if model == present_model else None
        for model in service.MODELS
    ]
    mock_connection(monkeypatch, [("85-00837106", *columns)])

    response = authenticated_client.get("/landing/")

    assert response.status_code == 200
    assert response.json() == [{
        "claim_number": "85-00837106",
        **{model: records if model == present_model else [] for model in service.MODELS},
    }]


def test_api_malformed_json_is_not_silently_replaced_with_empty_array(
    monkeypatch, authenticated_client
):
    mock_connection(monkeypatch, [("85-00837106", "broken-json", None, None, None)])
    response = authenticated_client.get("/landing/")
    assert response.status_code == 500
    assert response.json() == {"detail": {"error": "Database operation failed"}}


def test_api_requires_authentication():
    assert TestClient(app).get("/landing/").status_code == 401


def test_api_database_failure_is_sanitized(monkeypatch, authenticated_client):
    def fail():
        raise RuntimeError("private connection details")

    monkeypatch.setattr(service, "fetch_landing_claims", fail)
    response = authenticated_client.get("/landing/")
    assert response.status_code == 500
    assert response.json() == {"detail": {"error": "Database operation failed"}}

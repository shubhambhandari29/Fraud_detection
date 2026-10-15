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
    for model, (table, claim, prediction, action, details) in zip(
        service.MODELS, tables, strict=True
    ):
        base_columns = (claim, prediction, action, details, "Selected")
        extra_columns = tuple(
            column
            for _, column in service.FILTER_FIELDS[model]
            if column not in base_columns
        )
        connection.execute(
            f'CREATE TABLE [{table}] ([{claim}] TEXT, [{prediction}] TEXT, '
            f'[{action}] TEXT, [{details}] TEXT, [Selected] INTEGER'
            + "".join(f", [{column}]" for column in extra_columns)
            + ")"
        )

    def run(rows_by_model):
        for model, rows in rows_by_model.items():
            table, claim, prediction, action, details = tables[service.MODELS.index(model)]
            base_columns = (claim, prediction, action, details, "Selected")
            for row in rows:
                values, extras = row[:5], row[5] if len(row) > 5 else {}
                extra_columns = tuple(column for column in extras if column not in base_columns)
                columns = base_columns + extra_columns
                column_sql = ", ".join(f"[{column}]" for column in columns)
                placeholders = ", ".join("?" for _ in columns)
                connection.execute(
                    f"INSERT INTO [{table}] ({column_sql}) VALUES ({placeholders})",
                    (*values, *(extras[column] for column in extra_columns)),
                )
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
    core_rows = [row[:5] for row in rows]
    assert core_rows.count(("litigation", "85-00837106", "02", "Low", "Action B")) == 2
    assert ("fraud", "85-00837106", None, "High", "Status — Feedback") in core_rows
    assert (
        "litigation", "85-00837106", "01", "High", "Action A — Details A"
    ) in core_rows
    assert ("severity", "85-00837106", None, "Low", "Medical Report") in core_rows
    assert ("subrogation", "85-00837106", None, "High", "Assigned") in core_rows


@pytest.mark.parametrize("prediction", [None, "", "NULL", "unexpected"])
def test_sql_missing_predictions_actions_and_whitespace(sql_source, prediction):
    rows = sql_source({"litigation": [
        (" 85-00837106-01 ", prediction, " ", "NULL", 1)
    ]})
    assert [row[:5] for row in rows] == [("litigation", "85-00837106", "01", None, None)]


def test_sql_keeps_claim_number_without_feature_suffix(sql_source):
    rows = sql_source({"litigation": [
        ("85-00837106", "  high  ", None, " Detail only ", 1)
    ]})
    assert [row[:5] for row in rows] == [
        ("litigation", "85-00837106", None, "High", "Detail only")
    ]


def test_sql_splits_short_litigation_claim_and_feature_example(sql_source):
    rows = sql_source({"litigation": [
        ("8754323-02", "1: High", "Review", None, 1)
    ]})
    assert [row[:5] for row in rows] == [("litigation", "8754323", "02", "High", "Review")]


def with_filter_keys(model, recommendation):
    return {
        **{key: None for key, _ in service.FILTER_FIELDS[model]},
        **recommendation,
    }


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
            return [
                (*row, *(None for _ in service.FILTER_COLUMNS))
                if len(row) == 5 else row
                for row in sql_rows
            ]

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
        {
            "Feature": "01",
            "Predictions": "High",
            "Action": 'Review "medical"\nreport — café',
        },
        {"Feature": "02", "Predictions": "Low", "Action": None},
        {"Feature": "02", "Predictions": "Low", "Action": None},
    ]
    mock_connection(monkeypatch, [
        *(('litigation', '85-00837106', r['Feature'], r['Predictions'], r['Action'])
          for r in recommendations),
        ("fraud", "85-00937608", None, None, None),
    ])
    response = authenticated_client.get("/landing/")
    assert response.status_code == 200
    assert response.json() == [
        {"claim_number": "85-00837106", "fraud": [],
         "litigation": [with_filter_keys("litigation", row) for row in recommendations],
         "severity": [], "subrogation": []},
        {"claim_number": "85-00937608",
         "fraud": [with_filter_keys("fraud", {"Predictions": None, "Action": None})],
         "litigation": [], "severity": [], "subrogation": []},
    ]


def test_api_returns_each_models_filter_values_on_its_own_row(
    sql_source, monkeypatch, authenticated_client
):
    rows = sql_source({
        "fraud": [(
            "85-00837106", "1: High", "Review", "Refer to analyst", 1,
            {
                "REFERRAL_MECHANISM": "Manual",
                "CTS_TABLE": "Y",
                "ANALYST_NAME": "Analyst A",
                "CARPE_STATUS": "N",
                "low_apd_pay": 125.5,
                "IES_FLAG": "Y",
            },
        )],
        "litigation": [(
            "85-00837106-02", "0: Low", "Monitor", "Await documents", 1,
            {
                "MANAGER_FULL_NM": "Manager L",
                "ADJUSTER_FULL_NM": "Adjuster L",
                "New_Updates": "No",
                "Addressed": "True",
                "Litigation_Pred_By_Model": "Yes",
                "SEVERITY_REVIEWED": "No",
            },
        )],
        "severity": [
            (
                "85-00837106", "1: High", "Review", "Raise reserve", 1,
                {
                    "MANAGER_FULL_NM": "Manager S",
                    "ADJUSTER_FULL_NM": "Adjuster S",
                    "New_Updates": "Yes",
                    "Threshold_Filter": "< $75000",
                    "Percentage_Bucket": "10%-20%",
                },
            ),
            (
                "85-00837106", "0: Low", None, None, 1,
                {"Threshold_Filter": ">= $75000"},
            ),
        ],
        "subrogation": [(
            "85-00837106", "0: Low", "Pending", None, 1,
            {
                "ACT_ASGNED_USER_FULL_NM": "Manager A",
                "State_Group": "NY",
                "PAID_FINAL_IND": "No",
                "Subro_hist_flag": "Yes",
                "SUBJ_TXT": "Recovery review",
                "SubroGroup_IND": "Subrogation",
            },
        )],
    })
    mock_connection(monkeypatch, rows)

    response = authenticated_client.get("/landing/")

    assert response.status_code == 200
    claim = response.json()[0]
    assert claim["fraud"] == [{
        "Predictions": "High", "Action": "Review — Refer to analyst",
        "referralMechanism": "Manual", "ctsStatus": "Y", "user": "Analyst A",
        "carpeStatus": "N", "lowImpact": 125.5, "iesFlag": "Y",
    }]
    assert claim["litigation"] == [{
        "Predictions": "Low", "Action": "Monitor — Await documents", "Feature": "02",
        "unitManager": "Manager L", "adjuster": "Adjuster L", "action": "Monitor",
        "newUpdates": "No", "reviewed": "True", "predictedByModel": "Yes",
        "reviewedInSeverity": "No",
    }]
    assert claim["severity"] == [
        {
            "Predictions": "High", "Action": "Review — Raise reserve",
            "unitManager": "Manager S", "adjuster": "Adjuster S", "action": "Review",
            "newUpdates": "Yes", "reserveThreshold": "< $75000",
            "reserveChange": "10%-20%",
        },
        {
            "Predictions": "Low", "Action": None,
            "unitManager": None, "adjuster": None, "action": None,
            "newUpdates": None, "reserveThreshold": ">= $75000",
            "reserveChange": None,
        },
    ]
    assert claim["subrogation"] == [{
        "Predictions": "Low", "Action": "Pending",
        "assignActMgr": "Manager A", "accidentState": "NY", "paymentMade": "No",
        "histSubroGrpAssign": "Yes", "subjectText": "Recovery review",
        "crrAssignGrpName": "Subrogation", "reviewStatus": "Pending",
    }]


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
    feature = "01" if present_model == "litigation" else None
    if feature:
        records[0]["Feature"] = feature
    records = [with_filter_keys(present_model, record) for record in records]
    mock_connection(
        monkeypatch, [(present_model, "85-00837106", feature, None, None)]
    )

    response = authenticated_client.get("/landing/")

    assert response.status_code == 200
    assert response.json() == [{
        "claim_number": "85-00837106",
        **{model: records if model == present_model else [] for model in service.MODELS},
    }]


def test_api_invalid_prediction_is_not_silently_dropped(
    monkeypatch, authenticated_client
):
    mock_connection(
        monkeypatch, [("fraud", "85-00837106", None, "invalid", None)]
    )
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
            "fraud": [with_filter_keys(
                "fraud", {"Predictions": "High", "Action": "Status — Feedback"}
            )],
            "litigation": [
                with_filter_keys("litigation", {
                    "Feature": "01",
                    "Predictions": "High",
                    "Action": "Action A — Details A",
                    "action": "Action A",
                }),
                with_filter_keys("litigation", {
                    "Feature": "02", "Predictions": "Low", "Action": "Action B", "action": "Action B"
                }),
                with_filter_keys("litigation", {
                    "Feature": "02", "Predictions": "Low", "Action": "Action B", "action": "Action B"
                }),
            ],
            "severity": [
                with_filter_keys("severity", {
                    "Predictions": "High", "Action": "Settle", "action": "Settle"
                }),
                with_filter_keys("severity", {"Predictions": "Low", "Action": None}),
            ],
            "subrogation": [with_filter_keys(
                "subrogation", {
                    "Predictions": "High", "Action": "Assigned", "reviewStatus": "Assigned"
                }
            )],
        },
        {
            "claim_number": "85-00999999",
            "fraud": [], "litigation": [], "severity": [],
            "subrogation": [with_filter_keys(
                "subrogation", {"Predictions": "Low", "Action": None}
            )],
        },
    ]


def test_service_logs_phase_timings(monkeypatch, caplog):
    mock_connection(monkeypatch, [("fraud", "85-00837106", None, "High", None)])
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

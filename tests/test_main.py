import asyncio
from contextlib import contextmanager
from datetime import date, datetime
from types import SimpleNamespace

import pytest

from core import db_helpers
from core.models.third_party_auto import ClaimTransferRequest
from api.third_party_auto import claims, cts_users, user_roster
from app import app
from services.third_party_auto import claims_service, user_roster_service
from services.abi_litigation import claims_service as abi_claims_service
from services.auto_subrogation import claims_service as auto_subrogation_claims_service
from services.pal_severity import claims_service as pal_claims_service


class FakeCursor:
    def __init__(self, columns):
        self.columns = columns
        self.description = []
        self.executed = []

    def execute(self, query, params=None):
        self.executed.append((query, params))
        if query.startswith("SELECT TOP 0"):
            self.description = [(column,) for column in self.columns]
        return self

    def fetchall(self):
        return []

    def fetchone(self):
        return None


class FakeConnection:
    def __init__(self, columns):
        self.fake_cursor = FakeCursor(columns)
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return self.fake_cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def use_connection(monkeypatch, connection):
    @contextmanager
    def fake_db_connection():
        yield connection

    monkeypatch.setattr(db_helpers, "db_connection", fake_db_connection)


@pytest.mark.parametrize(
    ("module", "endpoint_name", "service_name"),
    [
        (claims, "upsert_claims", "upsert_claims_service"),
        (cts_users, "upsert_cts_users", "upsert_cts_users_service"),
        (user_roster, "upsert_user_roster", "upsert_user_roster_service"),
    ],
)
def test_upsert_api_accepts_direct_record(
    monkeypatch, module, endpoint_name, service_name
):
    payload = {"ID": "102", "Status": "Dismissed"}
    received = None

    async def fake_service(records, *args):
        nonlocal received
        received = records
        return {"message": "Upsert successful", "count": 1}

    monkeypatch.setattr(module, service_name, fake_service)

    if module is claims:
        current_user = SimpleNamespace(user=SimpleNamespace(id="user@hanover.com"))
        result = asyncio.run(getattr(module, endpoint_name)(payload, current_user))
    else:
        result = asyncio.run(getattr(module, endpoint_name)(payload))

    assert received == [payload]
    assert result == {"message": "Upsert successful", "count": 1}


def test_claim_upsert_builds_parameterized_merge(monkeypatch):
    connection = FakeConnection(["ID", "Status", "Feedback Notes"])
    use_connection(monkeypatch, connection)

    result = db_helpers.merge_upsert_records(
        "dbo.tblFraudThirdPartyAutoBIEDW_OpenClaims_Predictions_Selector",
        [{"ID": "claim-1", "Status": "Pending", "Feedback Notes": "Review"}],
        "ID",
    )

    query, params = connection.fake_cursor.executed[-1]
    assert "MERGE INTO [dbo].[tblFraudThirdPartyAutoBIEDW_OpenClaims_Predictions_Selector]" in query
    assert "target.[ID] = source.[ID]" in query
    assert params == ["claim-1", "Pending", "Review"]
    assert connection.committed
    assert result["count"] == 1


def test_roster_record_without_identity_uses_insert(monkeypatch):
    connection = FakeConnection(["ID", "ANALYST_NAME", "ASSIGNMENT_STATUS"])
    use_connection(monkeypatch, connection)

    db_helpers.merge_upsert_records(
        "dbo.tblFraudThirdPartyAutoBIEDW_Roster",
        [{"ANALYST_NAME": "Analyst", "ASSIGNMENT_STATUS": "Active"}],
        "ID",
        identity_key=True,
    )

    query, params = connection.fake_cursor.executed[-1]
    assert query.startswith("INSERT INTO [dbo].[tblFraudThirdPartyAutoBIEDW_Roster]")
    assert params == ["Analyst", "Active"]


def test_get_user_roster_uses_roster_table(monkeypatch):
    received = {}

    async def fake_fetch_records_async(table, **kwargs):
        received.update(table=table, **kwargs)
        return [{"ID": 1, "ANALYST_NAME": "Analyst"}]

    monkeypatch.setattr(
        user_roster_service, "fetch_records_async", fake_fetch_records_async
    )

    result = asyncio.run(user_roster_service.get_user_roster())

    assert result == [{"ID": 1, "ANALYST_NAME": "Analyst"}]
    assert received == {
        "table": "dbo.tblFraudThirdPartyAutoBIEDW_Roster",
    }


def test_unknown_column_is_rejected_and_rolled_back(monkeypatch):
    connection = FakeConnection(["ID", "Status"])
    use_connection(monkeypatch, connection)

    with pytest.raises(ValueError, match="Unknown column"):
        db_helpers.merge_upsert_records(
            "dbo.tblFraudThirdPartyAutoBIEDW_OpenClaims_Predictions_Selector",
            [{"ID": "1", "NotAColumn": "value"}],
            "ID",
        )

    assert connection.rolled_back


def test_claim_requires_id(monkeypatch):
    connection = FakeConnection(["ID", "Status"])
    use_connection(monkeypatch, connection)

    with pytest.raises(ValueError, match="Missing required upsert key: ID"):
        db_helpers.merge_upsert_records(
            "dbo.tblFraudThirdPartyAutoBIEDW_OpenClaims_Predictions_Selector",
            [{"Status": "Pending"}],
            "ID",
        )


def test_fetch_records_applies_parameterized_status_filter(monkeypatch):
    connection = FakeConnection(["ID", "Status"])
    use_connection(monkeypatch, connection)

    db_helpers.fetch_records("dbo.Claims", filters={"Status": "Pending"})

    query, params = connection.fake_cursor.executed[-1]
    assert "WHERE [Status] = ?" in query
    assert "OFFSET" not in query
    assert params == ["Pending"]


@pytest.mark.parametrize(
    ("filters", "expected_filters"),
    [
        (None, None),
        ({"Status": "Pending"}, {"Status": "Pending"}),
        ({"Status": "Blank"}, {"Status": ""}),
        ({"Addressed": "true"}, {"Addressed": "True"}),
        ({"Addressed": "FALSE"}, {"Addressed": "False"}),
        (
            {"Status": "Assigned", "Addressed": "true", "Selected": "1"},
            {"Status": "Assigned", "Addressed": "True", "Selected": "1"},
        ),
    ],
)
def test_get_claims_maps_filters(monkeypatch, filters, expected_filters):
    received = {}

    async def fake_fetch_records_async(table, **kwargs):
        received.update(table=table, **kwargs)
        return []

    monkeypatch.setattr(claims_service, "fetch_records_async", fake_fetch_records_async)

    assert asyncio.run(claims_service.get_claims(filters)) == []
    assert received == {
        "table": claims_service.TABLE_NAME,
        "filters": expected_filters,
        "validate_filters": True,
        "allow_not_equal_filters": True,
        "sort_order": None,
    }


def test_fetch_records_combines_multiple_filters(monkeypatch):
    connection = FakeConnection(["ID", "Status", "Addressed"])
    use_connection(monkeypatch, connection)

    db_helpers.fetch_records(
        "dbo.Claims",
        filters={"Status": "Assigned", "Addressed": "True"},
    )

    query, params = connection.fake_cursor.executed[-1]
    assert "WHERE [Status] = ? AND [Addressed] = ?" in query
    assert "OFFSET" not in query
    assert params == ["Assigned", "True"]


def test_fetch_records_supports_ui_not_equal_filter_syntax(monkeypatch):
    connection = FakeConnection(
        ["Addressed", "Selected", "Status", "REFERRAL_MECHANISM"]
    )
    use_connection(monkeypatch, connection)

    db_helpers.fetch_records(
        "dbo.Claims",
        filters={
            "Addressed": "False",
            "Selected": "1",
            "Status": "<>Monitor",
            "REFERRAL_MECHANISM": "<>'No Referral'",
        },
        validate_filters=True,
        allow_not_equal_filters=True,
    )

    query, params = connection.fake_cursor.executed[-1]
    assert "[Addressed] = ?" in query
    assert "[Selected] = ?" in query
    assert "[Status] <> ?" in query
    assert "[REFERRAL_MECHANISM] <> ?" in query
    assert params == ["False", "1", "Monitor", "No Referral"]


def test_get_claims_returns_date_addressed_without_time(monkeypatch):
    async def fake_fetch_records_async(table, **kwargs):
        return [
            {"ID": "1", "Date Addressed": datetime(2026, 8, 24, 14, 30, 45)},
            {"ID": "2", "Date Addressed": None},
        ]

    monkeypatch.setattr(claims_service, "fetch_records_async", fake_fetch_records_async)

    result = asyncio.run(claims_service.get_claims({"Addressed": "true"}))

    assert result == [
        {"ID": "1", "Date Addressed": "2026-08-24"},
        {"ID": "2", "Date Addressed": None},
    ]


def test_date_serializer_formats_all_date_types():
    records = [
        {
            "Date Addressed": datetime(2026, 8, 24, 14, 30, 45),
            "MODEL_RUN_DATE": date(2026, 8, 20),
            "Status": "Pending",
            "Optional Date": None,
        }
    ]

    assert db_helpers.serialize_record_dates(records) == [
        {
            "Date Addressed": "2026-08-24",
            "MODEL_RUN_DATE": "2026-08-20",
            "Status": "Pending",
            "Optional Date": None,
        }
    ]


@pytest.mark.parametrize(
    ("service", "expected_table", "validates_filters"),
    [
        (
            abi_claims_service,
            "dbo.tblALLitigation_OpenClaimsPredictions_Selector",
            True,
        ),
        (
            pal_claims_service,
            "dbo.tblPALSeverity_OpenClaimsPredictions_Selector_GAME",
            False,
        ),
        (
            auto_subrogation_claims_service,
            "dbo.tblAutoSubro_combinedOpenClaimsPredictions_Selector",
            True,
        ),
    ],
)
def test_new_app_get_uses_expected_table_and_formats_dates(
    monkeypatch, service, expected_table, validates_filters
):
    received = {}

    async def fake_fetch_records_async(table, **kwargs):
        received.update(table=table, **kwargs)
        return [{"ID": 1, "RUN_DATE": datetime(2026, 7, 15, 18, 44, 50)}]

    monkeypatch.setattr(service, "fetch_records_async", fake_fetch_records_async)

    result = asyncio.run(service.get_claims())

    assert result == [{"ID": 1, "RUN_DATE": "2026-07-15"}]
    expected = {
        "table": expected_table,
        "filters": None,
        "allow_not_equal_filters": True,
        "sort_order": None,
    }
    if validates_filters:
        expected["validate_filters"] = True
    assert received == expected


@pytest.mark.parametrize(
    ("service", "validates_filters"),
    [
        (abi_claims_service, True),
        (pal_claims_service, False),
        (auto_subrogation_claims_service, True),
    ],
)
def test_new_app_get_forwards_dynamic_filters(
    monkeypatch, service, validates_filters
):
    received = {}

    async def fake_fetch_records_async(table, **kwargs):
        received.update(table=table, **kwargs)
        return []

    monkeypatch.setattr(service, "fetch_records_async", fake_fetch_records_async)

    filters = {"Addressed": "True", "Selected": "1"}
    assert asyncio.run(service.get_claims(filters)) == []
    assert received["filters"] == filters
    assert received.get("validate_filters", False) is validates_filters
    assert received["allow_not_equal_filters"] is True


@pytest.mark.parametrize(
    "service",
    [
        claims_service,
        abi_claims_service,
        pal_claims_service,
        auto_subrogation_claims_service,
    ],
)
def test_claim_get_extracts_sort_order_from_filters(monkeypatch, service):
    received = {}

    async def fake_fetch_records_async(table, **kwargs):
        received.update(table=table, **kwargs)
        return []

    monkeypatch.setattr(service, "fetch_records_async", fake_fetch_records_async)

    filters = {
        "Selected": "1",
        "Sort_Order": "ML_SCORE: Descending, IES: Ascending",
    }
    assert asyncio.run(service.get_claims(filters)) == []
    assert received["filters"] == {"Selected": "1"}
    assert received["sort_order"] == (
        "ML_SCORE: Descending, IES: Ascending"
    )


def test_fetch_records_applies_multi_column_sort_order(monkeypatch):
    connection = FakeConnection(["Selected", "ML_SCORE", "IES"])
    use_connection(monkeypatch, connection)

    db_helpers.fetch_records(
        "dbo.Claims",
        filters={"Selected": "1"},
        validate_filters=True,
        sort_order="ML_SCORE: Descending, IES: Ascending",
    )

    query, params = connection.fake_cursor.executed[-1]
    assert "WHERE [Selected] = ?" in query
    assert "ORDER BY [ML_SCORE] DESC, [IES] ASC" in query
    assert params == ["1"]


@pytest.mark.parametrize(
    "sort_order",
    ["ML_SCORE", "ML_SCORE: sideways", "ML_SCORE; DROP TABLE Claims: Descending"],
)
def test_fetch_records_rejects_invalid_sort_order(monkeypatch, sort_order):
    connection = FakeConnection(["ML_SCORE"])
    use_connection(monkeypatch, connection)

    with pytest.raises(ValueError, match="Sort_Order|Invalid SQL identifier"):
        db_helpers.fetch_records("dbo.Claims", sort_order=sort_order)


def test_validated_filters_use_real_column_names_and_parameters(monkeypatch):
    connection = FakeConnection(["ID", "Addressed", "MANAGER_FULL_NM"])
    use_connection(monkeypatch, connection)

    db_helpers.fetch_records(
        "dbo.Claims",
        filters={"addressed": "True", "manager_full_nm": "Jane Doe"},
        validate_filters=True,
    )

    query, params = connection.fake_cursor.executed[-1]
    assert "WHERE [Addressed] = ? AND [MANAGER_FULL_NM] = ?" in query
    assert params == ["True", "Jane Doe"]


def test_validated_filters_reject_unknown_columns(monkeypatch):
    connection = FakeConnection(["ID", "Addressed"])
    use_connection(monkeypatch, connection)

    with pytest.raises(ValueError, match="Unknown filter column.*NotAColumn"):
        db_helpers.fetch_records(
            "dbo.Claims",
            filters={"NotAColumn": "value"},
            validate_filters=True,
        )


def test_dynamic_filter_matches_physical_column_with_trailing_whitespace(monkeypatch):
    connection = FakeConnection(["Threshold_Filter "])
    use_connection(monkeypatch, connection)

    db_helpers.fetch_records(
        "dbo.Claims",
        filters={"Threshold_Filter": "< $75000"},
        validate_filters=True,
    )

    assert len(connection.fake_cursor.executed) == 2
    query, params = connection.fake_cursor.executed[-1]
    assert "WHERE [Threshold_Filter ] = ?" in query
    assert params == ["< $75000"]


def test_sql_server_unknown_filter_column_is_reported_as_value_error(monkeypatch):
    class InvalidColumnCursor(FakeCursor):
        def execute(self, query, params=None):
            raise db_helpers.PyodbcError("42S22", "Invalid column name 'Missing'")

    connection = FakeConnection([])
    connection.fake_cursor = InvalidColumnCursor([])
    use_connection(monkeypatch, connection)

    with pytest.raises(ValueError, match="Unknown filter column.*Missing"):
        db_helpers.fetch_records(
            "dbo.Claims",
            filters={"Missing": "value"},
        )


@pytest.mark.parametrize(
    "service",
    [claims_service, abi_claims_service, auto_subrogation_claims_service],
)
def test_claim_upsert_uses_id_key_and_authenticated_user(monkeypatch, service):
    received = {}

    async def fake_merge_upsert_records_async(table, records, key_column, **kwargs):
        received.update(
            table=table,
            records=records,
            key_column=key_column,
            **kwargs,
        )
        return {"message": "Upsert successful", "count": 1}

    monkeypatch.setattr(
        service,
        "merge_upsert_records_async",
        fake_merge_upsert_records_async,
    )

    payload = [{"ID": 7, "Action": "Dismiss"}]
    result = asyncio.run(service.upsert_claims(payload, "user@hanover.com"))

    assert result == {"message": "Upsert successful", "count": 1}
    assert received["records"] == payload
    assert received["key_column"] == "ID"
    assert received["audit_user_id"] == "user@hanover.com"


def configure_pal_transaction(monkeypatch, existing_claim, inserted_referrals):
    connection = FakeConnection([])

    @contextmanager
    def fake_db_connection():
        yield connection

    monkeypatch.setattr(pal_claims_service, "db_connection", fake_db_connection)
    monkeypatch.setattr(
        pal_claims_service,
        "_get_table_columns",
        lambda cursor, table: set(existing_claim)
        | {
            "ID",
            "Action",
            "INSERTDATE",
            "MODEL",
        },
    )
    monkeypatch.setattr(pal_claims_service, "_validate_record", lambda *args: None)
    monkeypatch.setattr(pal_claims_service, "_get_claim_record", lambda *args: existing_claim)
    monkeypatch.setattr(pal_claims_service, "_merge_record", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        pal_claims_service,
        "_insert_fastbreak_if_missing",
        lambda cursor, referral: inserted_referrals.append(referral),
    )
    return connection


def test_pal_fastbreak_upsert_conditionally_builds_referral(monkeypatch):
    existing_claim = {
        "ID": 7,
        "Action": "Pending",
        "DERIVE_CLM_FTR_NBR": "C100-01",
        "CLM_NBR": "C100",
        "CLM_FTR_NBR": "01",
        "FTR_CREAT_DT": date(2026, 9, 1),
        "CLM_LOB_DESC": "PAL",
        "FTR_TYPE_DESC": "BI",
        "FTR_COVG_TYPE_DESC": "Coverage",
        "ACDNT_ST_ABBR": "MA",
        "DT_OF_LOSS": date(2026, 8, 1),
        "OUTSTANDINGLOSSES": 80000,
        "FTR_ASGNED_USER_FIRST_NM": "Jane",
        "FTR_ASGNED_USER_LAST_NM": "Doe",
        "FTR_ASGNED_GRP_NM": "Claims",
    }
    inserted_referrals = []
    connection = configure_pal_transaction(
        monkeypatch, existing_claim, inserted_referrals
    )

    result = pal_claims_service.upsert_claims_transaction(
        [{"ID": 7, "Action": "Fastbreak"}],
        "user@hanover.com",
    )

    assert result == {"message": "Upsert successful", "count": 1}
    assert connection.committed
    assert not connection.rolled_back
    assert len(inserted_referrals) == 1
    assert inserted_referrals[0]["DERIVE_CLM_FTR_NBR"] == "C100-01"
    assert inserted_referrals[0]["MODEL"] == "PAL_Severity"
    assert isinstance(inserted_referrals[0]["INSERTDATE"], datetime)


def test_pal_non_fastbreak_upsert_does_not_create_referral(monkeypatch):
    inserted_referrals = []
    connection = configure_pal_transaction(
        monkeypatch,
        {"ID": 7, "Action": "Pending"},
        inserted_referrals,
    )

    pal_claims_service.upsert_claims_transaction(
        [{"ID": 7, "Action": "Dismiss"}],
        "user@hanover.com",
    )

    assert connection.committed
    assert inserted_referrals == []


def test_pal_upsert_rolls_back_when_fastbreak_insert_fails(monkeypatch):
    inserted_referrals = []
    connection = configure_pal_transaction(
        monkeypatch,
        {
            "ID": 7,
            "Action": "Pending",
            "DERIVE_CLM_FTR_NBR": "C100-01",
        },
        inserted_referrals,
    )
    monkeypatch.setattr(
        pal_claims_service,
        "_insert_fastbreak_if_missing",
        lambda *args: (_ for _ in ()).throw(RuntimeError("insert failed")),
    )

    with pytest.raises(RuntimeError, match="insert failed"):
        pal_claims_service.upsert_claims_transaction(
            [{"ID": 7, "Action": "Fastbreak"}],
            "user@hanover.com",
        )

    assert connection.rolled_back
    assert not connection.committed


def test_pal_fastbreak_insert_uses_atomic_duplicate_guard():
    cursor = FakeCursor([])
    referral = {
        "DERIVE_CLM_FTR_NBR": "C100-01",
        "CLM_NBR": "C100",
        "MODEL": "PAL_Severity",
    }

    pal_claims_service._insert_fastbreak_if_missing(cursor, referral)

    query, params = cursor.executed[-1]
    assert "IF NOT EXISTS" in query
    assert "WITH (UPDLOCK, HOLDLOCK)" in query
    assert "[dbo].[tblSeverity_Fastbreak_Referral]" in query
    assert params == ["C100-01", "C100-01", "C100", "PAL_Severity"]


def test_last_updated_by_entry_uses_required_format():
    assert db_helpers.format_last_updated_by_entry(
        "user@hanover.com",
        datetime(2026, 9, 9, 15, 50),
    ) == "user@hanover.com-9/09/2026 3:50PM;"


def test_claim_merge_sets_server_owned_last_updated_by(monkeypatch):
    connection = FakeConnection(["ID", "Action", "Last Updated By"])
    use_connection(monkeypatch, connection)

    db_helpers.merge_upsert_records(
        "dbo.Claims",
        [{"ID": 7, "Action": "Dismiss", "Last Updated By": "untrusted"}],
        "ID",
        audit_user_id="user@hanover.com",
    )

    query, params = connection.fake_cursor.executed[-1]
    assert "MERGE INTO [dbo].[Claims]" in query
    assert params[0:2] == [7, "Dismiss"]
    assert params[2].startswith("user@hanover.com-")
    assert params[2].endswith(";")
    assert "untrusted" not in params[2]


def test_claim_transfer_api_passes_payload_and_authenticated_user(monkeypatch):
    received = {}

    async def fake_transfer_service(target_user, claim_numbers, user_id):
        received.update(
            target_user=target_user,
            claim_numbers=claim_numbers,
            user_id=user_id,
        )
        return {"message": "Claim transfer successful", "count": 2}

    monkeypatch.setattr(claims, "transfer_claims_service", fake_transfer_service)
    current_user = SimpleNamespace(user=SimpleNamespace(id="user@hanover.com"))
    payload = ClaimTransferRequest(
        target_user="Jane Smith",
        claim_numbers=["101", "102"],
    )

    result = asyncio.run(claims.transfer_claims(payload, current_user))

    assert result == {"message": "Claim transfer successful", "count": 2}
    assert received == {
        "target_user": "Jane Smith",
        "claim_numbers": ["101", "102"],
        "user_id": "user@hanover.com",
    }


def test_claim_transfer_updates_by_claim_number_in_one_transaction(monkeypatch):
    class TransferCursor(FakeCursor):
        def fetchall(self):
            return [("101",), ("102",)]

    connection = FakeConnection([])
    connection.fake_cursor = TransferCursor([])

    @contextmanager
    def fake_db_connection():
        yield connection

    monkeypatch.setattr(claims_service, "db_connection", fake_db_connection)

    result = claims_service.transfer_claims_transaction(
        "Jane Smith",
        ["101", "102", "101"],
        "user@hanover.com",
    )

    query, params = connection.fake_cursor.executed[-1]
    assert "SET [ANALYST_NAME] = ?" in query
    assert "[Last Updated By] = ? + COALESCE([Last Updated By], '')" in query
    assert "WHERE [CLM_NBR] IN (?, ?)" in query
    assert params[0] == "Jane Smith"
    assert params[1].startswith("user@hanover.com-")
    assert params[2:] == ["101", "102"]
    assert result == {"message": "Claim transfer successful", "count": 2}
    assert connection.committed
    assert not connection.rolled_back


def test_claim_transfer_rolls_back_on_database_failure(monkeypatch):
    class FailingCursor(FakeCursor):
        def execute(self, query, params=None):
            raise RuntimeError("update failed")

    connection = FakeConnection([])
    connection.fake_cursor = FailingCursor([])

    @contextmanager
    def fake_db_connection():
        yield connection

    monkeypatch.setattr(claims_service, "db_connection", fake_db_connection)

    with pytest.raises(RuntimeError, match="update failed"):
        claims_service.transfer_claims_transaction(
            "Jane Smith",
            ["101"],
            "user@hanover.com",
        )

    assert connection.rolled_back
    assert not connection.committed


def test_new_app_routes_are_registered():
    paths = {route.path for route in app.routes}

    assert "/abi_litigation/" in paths
    assert "/abi_litigation/upsert" in paths
    assert "/pal_severity/" in paths
    assert "/pal_severity/upsert" in paths
    assert "/auto_subrogation/" in paths
    assert "/auto_subrogation/upsert" in paths
    assert "/claims/" in paths
    assert "/claims/upsert" in paths
    assert "/claims/transfer" in paths


def test_large_responses_use_gzip_and_swagger_highlighting_is_disabled():
    middleware_classes = {middleware.cls.__name__ for middleware in app.user_middleware}

    assert "GZipMiddleware" in middleware_classes
    assert app.swagger_ui_parameters["syntaxHighlight"] is False

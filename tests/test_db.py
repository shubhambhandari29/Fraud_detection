from __future__ import annotations

import struct
from datetime import datetime, timedelta

import pytest

import db


def test_build_connection_string_uses_fraud_database(monkeypatch):
    class DummySettings:
        DB_DRIVER = "{Driver}"
        DB_SERVER = "server"
        DB_NAME = "CLMDS_DataModelingAndTextMining"
        DB_AUTH = "auth"

    monkeypatch.setattr(db, "settings", DummySettings)

    connection_string = db._build_connection_string()

    assert "Driver={Driver};" in connection_string
    assert "Server=server;" in connection_string
    assert "Database=CLMDS_DataModelingAndTextMining;" in connection_string
    assert "Authentication=auth;" in connection_string
    assert connection_string.endswith("Encrypt=yes;TrustServerCertificate=no;")


def test_build_connection_string_accepts_database_override(monkeypatch):
    class DummySettings:
        DB_DRIVER = "{Driver}"
        DB_SERVER = "server"
        DB_NAME = "CLMDS_DataModelingAndTextMining"
        DB_AUTH = "auth"

    monkeypatch.setattr(db, "settings", DummySettings)

    connection_string = db._build_connection_string("CLMAA_FraudModel")

    assert "Database=CLMAA_FraudModel;" in connection_string


@pytest.mark.parametrize("name", ["DB_SERVER", "DB_AUTH"])
def test_build_connection_string_rejects_missing_required_settings(monkeypatch, name):
    class DummySettings:
        DB_DRIVER = "{Driver}"
        DB_SERVER = "server"
        DB_NAME = "CLMDS_DataModelingAndTextMining"
        DB_AUTH = "auth"

    setattr(DummySettings, name, None)
    monkeypatch.setattr(db, "settings", DummySettings)

    with pytest.raises(RuntimeError, match=name):
        db._build_connection_string()


def test_handle_datetimeoffset_parses_payload():
    value = struct.pack("<6hI2h", 2026, 8, 4, 12, 30, 5, 1234000, 5, 30)

    result = db._handle_datetimeoffset(memoryview(value))

    assert isinstance(result, datetime)
    assert result.microsecond == 1234
    assert result.utcoffset() == timedelta(hours=5, minutes=30)


def test_handle_datetimeoffset_returns_none_for_invalid_payload():
    assert db._handle_datetimeoffset(None) is None
    assert db._handle_datetimeoffset(b"invalid") is None


def test_get_raw_connection_configures_timeout_and_converter(monkeypatch):
    class FakeConnection:
        converter = None

        def add_output_converter(self, data_type, converter):
            self.converter = (data_type, converter)

    class FakePyodbc:
        SQL_SS_TIMESTAMPOFFSET = 123

        def __init__(self):
            self.connection = FakeConnection()
            self.arguments = None

        def connect(self, connection_string, *, timeout):
            self.arguments = (connection_string, timeout)
            return self.connection

    class DummySettings:
        DB_CONNECTION_TIMEOUT = 9

    fake_pyodbc = FakePyodbc()
    monkeypatch.setattr(db, "pyodbc", fake_pyodbc)
    monkeypatch.setattr(db, "settings", DummySettings)
    monkeypatch.setattr(
        db, "_build_connection_string", lambda database_name=None: "connection-string"
    )

    result = db.get_raw_connection()

    assert result is fake_pyodbc.connection
    assert fake_pyodbc.arguments == ("connection-string", 9)
    assert result.converter == (123, db._handle_datetimeoffset)


def test_db_connection_closes_connection(monkeypatch):
    class FakeConnection:
        closed = False

        def close(self):
            self.closed = True

    connection = FakeConnection()
    monkeypatch.setattr(db, "get_raw_connection", lambda database_name=None: connection)

    with db.db_connection() as yielded:
        assert yielded is connection
        assert not connection.closed

    assert connection.closed

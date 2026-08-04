"""SQL Server connection management."""

import struct
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pyodbc

from core.config import settings


def _required_setting(name: str, value: str | None) -> str:
    """Return a configured value or raise a useful error before connecting."""
    if value is None or not value.strip():
        raise RuntimeError(f"Missing required database setting: {name}")
    return value


def _build_connection_string() -> str:
    """Build the encrypted SQL Server ODBC connection string."""
    server = _required_setting("DB_SERVER", settings.DB_SERVER)
    authentication = _required_setting("DB_AUTH", settings.DB_AUTH)

    return (
        f"Driver={settings.DB_DRIVER};"
        f"Server={server};"
        f"Database={settings.DB_NAME};"
        f"Authentication={authentication};"
        "Encrypt=yes;"
        "TrustServerCertificate=no;"
    )


def _handle_datetimeoffset(
    dto_value: bytes | bytearray | memoryview | None,
) -> datetime | None:
    """Convert SQL Server datetimeoffset bytes to a timezone-aware datetime."""
    if dto_value is None:
        return None

    if isinstance(dto_value, memoryview):
        dto_value = dto_value.tobytes()

    try:
        if len(dto_value) == 20:
            year, month, day, hour, minute, second, fraction, tz_hour, tz_minute = (
                struct.unpack("<6hI2h", dto_value)
            )
            tzinfo = timezone(timedelta(hours=tz_hour, minutes=tz_minute))
        else:
            year, month, day, hour, minute, second, fraction, offset_minutes = (
                struct.unpack("<6hIh", dto_value)
            )
            tzinfo = timezone(timedelta(minutes=offset_minutes))
    except struct.error:
        return None

    return datetime(
        year,
        month,
        day,
        hour,
        minute,
        second,
        fraction // 1000,
        tzinfo=tzinfo,
    )


def get_raw_connection() -> pyodbc.Connection:
    """Open and return a new SQL Server connection."""
    connection = pyodbc.connect(
        _build_connection_string(),
        timeout=settings.DB_CONNECTION_TIMEOUT,
    )
    datetimeoffset_type = getattr(pyodbc, "SQL_SS_TIMESTAMPOFFSET", -155)
    try:
        connection.add_output_converter(datetimeoffset_type, _handle_datetimeoffset)
    except Exception:
        # Some ODBC drivers do not expose custom output converters.
        pass
    return connection


@contextmanager
def db_connection() -> Iterator[pyodbc.Connection]:
    """Yield a new connection and guarantee that it is closed afterward."""
    connection = get_raw_connection()
    try:
        yield connection
    finally:
        connection.close()

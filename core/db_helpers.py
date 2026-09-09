"""Reusable SQL Server read and upsert helpers."""

import re
from datetime import date, datetime
from functools import partial
from typing import Any

from fastapi.concurrency import run_in_threadpool
from pyodbc import Cursor

from db import db_connection


_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_ ]*$")
LAST_UPDATED_BY_COLUMN = "Last Updated By"


def serialize_record_dates(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return SQL records with every date/datetime represented as YYYY-MM-DD."""
    return [
        {
            column: value.date().isoformat()
            if isinstance(value, datetime)
            else value.isoformat()
            if isinstance(value, date)
            else value
            for column, value in record.items()
        }
        for record in records
    ]


def format_last_updated_by_entry(user_id: str, now: datetime | None = None) -> str:
    """Format a server-owned claim audit entry like user-9/09/2026 3:50PM;."""
    timestamp = now or datetime.now()
    hour = timestamp.hour % 12 or 12
    meridiem = "AM" if timestamp.hour < 12 else "PM"
    return (
        f"{user_id}-{timestamp.month}/{timestamp.day:02d}/{timestamp.year} "
        f"{hour}:{timestamp.minute:02d}{meridiem};"
    )


def _quote_identifier(identifier: str) -> str:
    if not _SAFE_IDENTIFIER.fullmatch(identifier):
        raise ValueError(f"Invalid SQL identifier: {identifier}")
    return f"[{identifier}]"


def _quote_table(table: str) -> str:
    parts = table.split(".")
    if len(parts) not in {1, 2}:
        raise ValueError(f"Invalid SQL table name: {table}")
    return ".".join(_quote_identifier(part) for part in parts)


def _get_table_columns(cursor: Cursor, table: str) -> set[str]:
    cursor.execute(f"SELECT TOP 0 * FROM {_quote_table(table)}")
    return {description[0] for description in cursor.description}


def _validate_record(record: dict[str, Any], allowed_columns: set[str]) -> None:
    if not record:
        raise ValueError("Records cannot be empty")

    unknown_columns = sorted(set(record) - allowed_columns)
    if unknown_columns:
        raise ValueError(f"Unknown column(s): {', '.join(unknown_columns)}")

    for column in record:
        _quote_identifier(column)


def fetch_records(
    table: str,
    *,
    filters: dict[str, Any] | None = None,
    validate_filters: bool = False,
    allow_not_equal_filters: bool = False,
) -> list[dict[str, Any]]:
    """Return all matching rows from a known service-owned table."""
    with db_connection() as connection:
        cursor = connection.cursor()
        filter_values: list[Any] = []
        query_parts = [f"SELECT * FROM {_quote_table(table)}"]
        if filters:
            if validate_filters:
                allowed_columns = _get_table_columns(cursor, table)
                columns_by_casefold = {
                    column.casefold(): column for column in allowed_columns
                }
                unknown_columns = sorted(
                    column
                    for column in filters
                    if column.casefold() not in columns_by_casefold
                )
                if unknown_columns:
                    raise ValueError(
                        f"Unknown filter column(s): {', '.join(unknown_columns)}"
                    )
                filters = {
                    columns_by_casefold[column.casefold()]: value
                    for column, value in filters.items()
                }

            clauses = []
            for column, value in filters.items():
                operator = "="
                if allow_not_equal_filters and isinstance(value, str):
                    if value.startswith("<>"):
                        operator = "<>"
                        value = value[2:]
                        if len(value) >= 2 and value[0] == value[-1] == "'":
                            value = value[1:-1]
                clauses.append(f"{_quote_identifier(column)} {operator} ?")
                filter_values.append(value)
            query_parts.append("WHERE " + " AND ".join(clauses))

        cursor.execute(
            " ".join(query_parts),
            filter_values,
        )
        columns = [description[0] for description in cursor.description]
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def _insert_record(cursor: Cursor, table: str, record: dict[str, Any]) -> None:
    columns = list(record)
    column_sql = ", ".join(_quote_identifier(column) for column in columns)
    placeholders = ", ".join("?" for _ in columns)
    cursor.execute(
        f"INSERT INTO {_quote_table(table)} ({column_sql}) VALUES ({placeholders})",
        [record[column] for column in columns],
    )


def _merge_record(
    cursor: Cursor,
    table: str,
    record: dict[str, Any],
    key_column: str,
    *,
    identity_key: bool,
) -> None:
    if key_column not in record:
        if identity_key:
            _insert_record(cursor, table, record)
            return
        raise ValueError(f"Missing required upsert key: {key_column}")

    columns = list(record)
    source_sql = ", ".join(
        f"? AS {_quote_identifier(column)}" for column in columns
    )
    update_columns = [column for column in columns if column != key_column]
    insert_columns = [
        column for column in columns if not (identity_key and column == key_column)
    ]
    key_sql = _quote_identifier(key_column)

    statements = [
        f"MERGE INTO {_quote_table(table)} AS target",
        f"USING (SELECT {source_sql}) AS source",
        f"ON target.{key_sql} = source.{key_sql}",
    ]
    if update_columns:
        assignments = ", ".join(
            f"target.{_quote_identifier(column)} = source.{_quote_identifier(column)}"
            for column in update_columns
        )
        statements.append(f"WHEN MATCHED THEN UPDATE SET {assignments}")
    if insert_columns:
        insert_sql = ", ".join(_quote_identifier(column) for column in insert_columns)
        values_sql = ", ".join(
            f"source.{_quote_identifier(column)}" for column in insert_columns
        )
        statements.append(
            f"WHEN NOT MATCHED THEN INSERT ({insert_sql}) VALUES ({values_sql})"
        )

    cursor.execute(
        "\n".join(statements) + ";",
        [record[column] for column in columns],
    )


def merge_upsert_records(
    table: str,
    records: list[dict[str, Any]],
    key_column: str,
    *,
    identity_key: bool = False,
    audit_user_id: str | None = None,
) -> dict[str, Any]:
    """Insert or update a batch in one transaction using a fixed key."""
    if not records:
        raise ValueError("At least one record is required")
    _quote_identifier(key_column)

    with db_connection() as connection:
        try:
            cursor = connection.cursor()
            allowed_columns = _get_table_columns(cursor, table)
            for submitted_record in records:
                record = dict(submitted_record)
                if audit_user_id is not None:
                    if LAST_UPDATED_BY_COLUMN not in allowed_columns:
                        raise ValueError(
                            f"Unknown audit column: {LAST_UPDATED_BY_COLUMN}"
                        )
                    existing_history = ""
                    if key_column in record:
                        cursor.execute(
                            f"SELECT {_quote_identifier(LAST_UPDATED_BY_COLUMN)} "
                            f"FROM {_quote_table(table)} "
                            f"WHERE {_quote_identifier(key_column)} = ?",
                            [record[key_column]],
                        )
                        existing_row = cursor.fetchone()
                        if existing_row and existing_row[0]:
                            existing_history = str(existing_row[0])
                    record[LAST_UPDATED_BY_COLUMN] = (
                        format_last_updated_by_entry(audit_user_id) + existing_history
                    )
                _validate_record(record, allowed_columns)
                _merge_record(
                    cursor,
                    table,
                    record,
                    key_column,
                    identity_key=identity_key,
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    return {"message": "Upsert successful", "count": len(records)}


async def fetch_records_async(
    table: str,
    *,
    filters: dict[str, Any] | None = None,
    validate_filters: bool = False,
    allow_not_equal_filters: bool = False,
) -> list[dict[str, Any]]:
    return await run_in_threadpool(
        partial(
            fetch_records,
            table=table,
            filters=filters,
            validate_filters=validate_filters,
            allow_not_equal_filters=allow_not_equal_filters,
        )
    )


async def merge_upsert_records_async(
    table: str,
    records: list[dict[str, Any]],
    key_column: str,
    *,
    identity_key: bool = False,
    audit_user_id: str | None = None,
) -> dict[str, Any]:
    return await run_in_threadpool(
        partial(
            merge_upsert_records,
            table=table,
            records=records,
            key_column=key_column,
            identity_key=identity_key,
            audit_user_id=audit_user_id,
        )
    )

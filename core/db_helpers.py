"""Reusable SQL Server read and upsert helpers."""

import re
from functools import partial
from typing import Any

from fastapi.concurrency import run_in_threadpool
from pyodbc import Cursor

from db import db_connection


_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_ ]*$")


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
    limit: int = 100,
    offset: int = 0,
    filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return a page of rows from a known service-owned table."""
    if not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")
    if offset < 0:
        raise ValueError("offset must be zero or greater")

    with db_connection() as connection:
        cursor = connection.cursor()
        filter_values: list[Any] = []
        where_sql = ""
        if filters:
            clauses = []
            for column, value in filters.items():
                clauses.append(f"{_quote_identifier(column)} = ?")
                filter_values.append(value)
            where_sql = " WHERE " + " AND ".join(clauses)

        cursor.execute(
            f"SELECT * FROM {_quote_table(table)} "
            f"{where_sql}"
            "ORDER BY (SELECT NULL) OFFSET ? ROWS FETCH NEXT ? ROWS ONLY",
            [*filter_values, offset, limit],
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
) -> dict[str, Any]:
    """Insert or update a batch in one transaction using a fixed key."""
    if not records:
        raise ValueError("At least one record is required")
    _quote_identifier(key_column)

    with db_connection() as connection:
        try:
            cursor = connection.cursor()
            allowed_columns = _get_table_columns(cursor, table)
            for record in records:
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
    limit: int = 100,
    offset: int = 0,
    filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    return await run_in_threadpool(
        partial(
            fetch_records,
            table=table,
            limit=limit,
            offset=offset,
            filters=filters,
        )
    )


async def merge_upsert_records_async(
    table: str,
    records: list[dict[str, Any]],
    key_column: str,
    *,
    identity_key: bool = False,
) -> dict[str, Any]:
    return await run_in_threadpool(
        partial(
            merge_upsert_records,
            table=table,
            records=records,
            key_column=key_column,
            identity_key=identity_key,
        )
    )

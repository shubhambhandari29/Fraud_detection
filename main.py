"""Small starter API for the Fraud application SQL tables.

Authentication and application-specific business rules are intentionally deferred.
"""

import re
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from pyodbc import Cursor

from db import db_connection


app = FastAPI(title="Fraud API", version="0.1.0")


@dataclass(frozen=True)
class TableSpec:
    sql_name: str
    key_column: str | None
    identity_key: bool = False


CLAIMS = TableSpec(
    sql_name="[dbo].[tblFraudThirdPartyAutoBIEDW_OpenClaims_Predictions_Selector]",
    key_column="ID",
)
ROSTER = TableSpec(
    sql_name="[dbo].[tblFraudThirdPartyAutoBIEDW_Roster]",
    key_column="ID",
    identity_key=True,
)
CTS_USERS = TableSpec(
    sql_name="[dbo].[tblFraudThirdPartyAutoBIEDW_CTS_UserName]",
    key_column=None,
)

_SAFE_COLUMN = re.compile(r"^[A-Za-z_][A-Za-z0-9_ ]*$")


class UpsertRequest(BaseModel):
    records: list[dict[str, Any]] = Field(min_length=1)


class WriteResult(BaseModel):
    message: str
    count: int


def _quote_column(column: str) -> str:
    if not _SAFE_COLUMN.fullmatch(column):
        raise ValueError(f"Invalid column name: {column}")
    return f"[{column}]"


def _table_columns(cursor: Cursor, table: TableSpec) -> set[str]:
    cursor.execute(f"SELECT TOP 0 * FROM {table.sql_name}")
    return {description[0] for description in cursor.description}


def _validate_columns(record: dict[str, Any], allowed_columns: set[str]) -> None:
    if not record:
        raise ValueError("Records cannot be empty")

    unknown = sorted(set(record) - allowed_columns)
    if unknown:
        raise ValueError(f"Unknown column(s): {', '.join(unknown)}")

    for column in record:
        _quote_column(column)


def _fetch_rows(table: TableSpec, limit: int, offset: int) -> list[dict[str, Any]]:
    with db_connection() as connection:
        cursor = connection.cursor()
        cursor.execute(
            f"SELECT * FROM {table.sql_name} "
            "ORDER BY (SELECT NULL) OFFSET ? ROWS FETCH NEXT ? ROWS ONLY",
            [offset, limit],
        )
        columns = [description[0] for description in cursor.description]
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def _insert_record(cursor: Cursor, table: TableSpec, record: dict[str, Any]) -> None:
    columns = list(record)
    column_sql = ", ".join(_quote_column(column) for column in columns)
    placeholders = ", ".join("?" for _ in columns)
    cursor.execute(
        f"INSERT INTO {table.sql_name} ({column_sql}) VALUES ({placeholders})",
        [record[column] for column in columns],
    )


def _merge_record(cursor: Cursor, table: TableSpec, record: dict[str, Any]) -> None:
    key = table.key_column
    if key is None:
        raise ValueError("This table does not support upserts")
    if key not in record:
        if table.identity_key:
            _insert_record(cursor, table, record)
            return
        raise ValueError(f"Missing required upsert key: {key}")

    columns = list(record)
    source_sql = ", ".join(f"? AS {_quote_column(column)}" for column in columns)
    update_columns = [column for column in columns if column != key]
    insert_columns = [
        column for column in columns if not (table.identity_key and column == key)
    ]

    statements = [
        f"MERGE INTO {table.sql_name} AS target",
        f"USING (SELECT {source_sql}) AS source",
        f"ON target.{_quote_column(key)} = source.{_quote_column(key)}",
    ]
    if update_columns:
        assignments = ", ".join(
            f"target.{_quote_column(column)} = source.{_quote_column(column)}"
            for column in update_columns
        )
        statements.append(f"WHEN MATCHED THEN UPDATE SET {assignments}")
    if insert_columns:
        insert_sql = ", ".join(_quote_column(column) for column in insert_columns)
        values_sql = ", ".join(
            f"source.{_quote_column(column)}" for column in insert_columns
        )
        statements.append(
            f"WHEN NOT MATCHED THEN INSERT ({insert_sql}) VALUES ({values_sql})"
        )

    cursor.execute("\n".join(statements) + ";", [record[column] for column in columns])


def _upsert_rows(table: TableSpec, records: list[dict[str, Any]]) -> WriteResult:
    with db_connection() as connection:
        try:
            cursor = connection.cursor()
            allowed_columns = _table_columns(cursor, table)
            for record in records:
                _validate_columns(record, allowed_columns)
                _merge_record(cursor, table, record)
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    return WriteResult(message="Upsert successful", count=len(records))


def _read(table: TableSpec, limit: int, offset: int) -> list[dict[str, Any]]:
    try:
        return _fetch_rows(table, limit, offset)
    except Exception as error:
        raise HTTPException(status_code=500, detail="Database operation failed") from error


def _upsert(table: TableSpec, request: UpsertRequest) -> WriteResult:
    try:
        return _upsert_rows(table, request.records)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=500, detail="Database operation failed") from error


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/claims")
def get_claims(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    return _read(CLAIMS, limit, offset)


@app.put("/api/claims", response_model=WriteResult)
def upsert_claims(request: UpsertRequest) -> WriteResult:
    return _upsert(CLAIMS, request)


@app.get("/api/analysts")
def get_analysts(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    return _read(ROSTER, limit, offset)


@app.put("/api/analysts", response_model=WriteResult)
def upsert_analysts(request: UpsertRequest) -> WriteResult:
    return _upsert(ROSTER, request)


@app.get("/api/cts-users")
def get_cts_users(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    return _read(CTS_USERS, limit, offset)

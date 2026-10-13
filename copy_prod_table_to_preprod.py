"""Refresh an existing PREPROD table from its PROD counterpart.

Change only DATABASE_NAME and TABLE_NAME below. Existing PREPROD columns are
left unchanged. Columns present in PROD but missing from PREPROD are added,
then PREPROD data is replaced with PROD data in one transaction.

The PROD connection uses ApplicationIntent=ReadOnly. The script does not
compare or alter the data types of columns that already exist in PREPROD.

Requires: pyodbc and Microsoft ODBC Driver 17 for SQL Server.
"""

from __future__ import annotations

import re
from typing import Any

import pyodbc


# Change only these two values. TABLE_NAME may include the schema.
DATABASE_NAME = "CLMAA_FraudModel"
TABLE_NAME = "dbo.tblFraudAutoDashboardEDW"

PROD_SERVER = "clms-prd-sqlmanagedinstance.445cfa5e0fe5.database.windows.net"
PREPROD_SERVER = "clms-preprd-sqlmanagedinstance.3b98dc354c37.database.windows.net"
ODBC_DRIVER = "{ODBC Driver 17 for SQL Server}"
AUTHENTICATION = "ActiveDirectoryInteractive"
BATCH_SIZE = 1_000
CONNECTION_TIMEOUT_SECONDS = 30

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_ $-]*$")


def quote_identifier(value: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"Unsafe SQL identifier: {value!r}")
    return f"[{value}]"


def parse_table_name(value: str) -> tuple[str, str]:
    parts = [part.strip() for part in value.split(".")]
    if len(parts) == 1:
        schema, table = "dbo", parts[0]
    elif len(parts) == 2:
        schema, table = parts
    else:
        raise ValueError("TABLE_NAME must be 'TableName' or 'schema.TableName'")
    quote_identifier(schema)
    quote_identifier(table)
    return schema, table


def connection_string(server: str, *, read_only: bool) -> str:
    parts = [
        f"Driver={ODBC_DRIVER}",
        f"Server={server}",
        f"Database={DATABASE_NAME}",
        f"Authentication={AUTHENTICATION}",
        "Encrypt=yes",
        "TrustServerCertificate=no",
        f"Connection Timeout={CONNECTION_TIMEOUT_SECONDS}",
    ]
    if read_only:
        parts.append("ApplicationIntent=ReadOnly")
    return ";".join(parts) + ";"


def connect(server: str, *, read_only: bool) -> pyodbc.Connection:
    return pyodbc.connect(connection_string(server, read_only=read_only), autocommit=False)


def table_exists(cursor: pyodbc.Cursor, schema: str, table: str) -> bool:
    cursor.execute(
        """
SELECT 1
FROM sys.tables AS t
JOIN sys.schemas AS s ON s.schema_id = t.schema_id
WHERE s.name = ? AND t.name = ?
""",
        [schema, table],
    )
    return cursor.fetchone() is not None


def fetch_columns(cursor: pyodbc.Cursor, schema: str, table: str) -> list[dict[str, Any]]:
    cursor.execute(
        """
SELECT
    c.column_id,
    c.name AS column_name,
    ty.name AS type_name,
    SCHEMA_NAME(ty.schema_id) AS type_schema,
    ty.is_user_defined,
    c.max_length,
    c.precision,
    c.scale,
    c.is_nullable,
    c.collation_name,
    c.is_identity,
    c.is_rowguidcol,
    c.is_sparse,
    c.generated_always_type,
    ic.seed_value,
    ic.increment_value,
    cc.definition AS computed_definition,
    cc.is_persisted,
    dc.definition AS default_definition
FROM sys.tables AS tb
JOIN sys.schemas AS s ON s.schema_id = tb.schema_id
JOIN sys.columns AS c ON c.object_id = tb.object_id
JOIN sys.types AS ty ON ty.user_type_id = c.user_type_id
LEFT JOIN sys.identity_columns AS ic
    ON ic.object_id = c.object_id AND ic.column_id = c.column_id
LEFT JOIN sys.computed_columns AS cc
    ON cc.object_id = c.object_id AND cc.column_id = c.column_id
LEFT JOIN sys.default_constraints AS dc
    ON dc.object_id = c.default_object_id
WHERE s.name = ? AND tb.name = ?
ORDER BY c.column_id
""",
        [schema, table],
    )
    names = [description[0] for description in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def sql_type(column: dict[str, Any]) -> str:
    type_name = str(column["type_name"])
    lowered = type_name.casefold()
    if column["is_user_defined"]:
        return f"{quote_identifier(str(column['type_schema']))}." f"{quote_identifier(type_name)}"
    if lowered in {"varchar", "char", "varbinary", "binary"}:
        length = "MAX" if column["max_length"] == -1 else str(column["max_length"])
        return f"{quote_identifier(type_name)}({length})"
    if lowered in {"nvarchar", "nchar"}:
        length = "MAX" if column["max_length"] == -1 else str(int(column["max_length"]) // 2)
        return f"{quote_identifier(type_name)}({length})"
    if lowered in {"decimal", "numeric"}:
        return f"{quote_identifier(type_name)}" f"({column['precision']},{column['scale']})"
    if lowered in {"datetime2", "datetimeoffset", "time"}:
        return f"{quote_identifier(type_name)}({column['scale']})"
    if lowered == "float":
        return f"{quote_identifier(type_name)}({column['precision']})"
    return quote_identifier(type_name)


def column_definition(column: dict[str, Any]) -> str:
    name = quote_identifier(str(column["column_name"]))
    computed = column["computed_definition"]
    if computed is not None:
        persisted = " PERSISTED" if column["is_persisted"] else ""
        return f"{name} AS {computed}{persisted}"
    if column["generated_always_type"]:
        raise RuntimeError(f"Cannot add generated column {column['column_name']!r} automatically")

    pieces = [name, sql_type(column)]
    if column["collation_name"]:
        pieces.extend(["COLLATE", str(column["collation_name"])])
    if column["is_sparse"]:
        pieces.append("SPARSE")
    if column["is_rowguidcol"]:
        pieces.append("ROWGUIDCOL")
    if column["is_identity"]:
        seed = column["seed_value"] or 1
        increment = column["increment_value"] or 1
        pieces.append(f"IDENTITY({seed},{increment})")
    pieces.append("NULL" if column["is_nullable"] else "NOT NULL")
    if column["default_definition"] is not None:
        pieces.extend(["DEFAULT", str(column["default_definition"])])
    return " ".join(pieces)


def add_missing_columns(
    cursor: pyodbc.Cursor,
    schema: str,
    table: str,
    prod_columns: list[dict[str, Any]],
    preprod_columns: list[dict[str, Any]],
) -> list[str]:
    """Add PROD columns that do not already exist in PREPROD."""
    qualified = f"{quote_identifier(schema)}.{quote_identifier(table)}"
    existing = {str(column["column_name"]).strip().casefold() for column in preprod_columns}
    added: list[str] = []
    for column in prod_columns:
        name = str(column["column_name"])
        if name.strip().casefold() in existing:
            continue
        cursor.execute(f"ALTER TABLE {qualified} ADD {column_definition(column)}")
        added.append(name)
    return added


def row_count(cursor: pyodbc.Cursor, qualified_table: str) -> int:
    cursor.execute(f"SELECT COUNT_BIG(*) FROM {qualified_table}")
    return int(cursor.fetchone()[0])


def copy_rows(
    prod_cursor: pyodbc.Cursor,
    preprod_cursor: pyodbc.Cursor,
    qualified_table: str,
    prod_columns: list[dict[str, Any]],
    preprod_columns: list[dict[str, Any]],
) -> int:
    preprod_by_name = {
        str(column["column_name"]).strip().casefold(): column for column in preprod_columns
    }
    insertable = [
        column
        for column in prod_columns
        if column["computed_definition"] is None
        and str(column["type_name"]).casefold() not in {"timestamp", "rowversion"}
        and str(column["column_name"]).strip().casefold() in preprod_by_name
        and preprod_by_name[str(column["column_name"]).strip().casefold()]["computed_definition"]
        is None
    ]
    if not insertable:
        return 0

    column_sql = ", ".join(quote_identifier(str(column["column_name"])) for column in insertable)
    placeholders = ", ".join("?" for _ in insertable)
    prod_cursor.execute(f"SELECT {column_sql} FROM {qualified_table}")
    insert_sql = f"INSERT INTO {qualified_table} ({column_sql}) VALUES ({placeholders})"
    has_identity = any(
        preprod_by_name[str(column["column_name"]).strip().casefold()]["is_identity"]
        for column in insertable
    )

    preprod_cursor.fast_executemany = True
    if has_identity:
        preprod_cursor.execute(f"SET IDENTITY_INSERT {qualified_table} ON")
    copied = 0
    try:
        while True:
            rows = prod_cursor.fetchmany(BATCH_SIZE)
            if not rows:
                break
            preprod_cursor.executemany(insert_sql, rows)
            copied += len(rows)
            print(f"Copied {copied:,} rows...", flush=True)
    finally:
        if has_identity:
            preprod_cursor.execute(f"SET IDENTITY_INSERT {qualified_table} OFF")
    return copied


def main() -> None:
    schema, table = parse_table_name(TABLE_NAME)
    qualified = f"{quote_identifier(schema)}.{quote_identifier(table)}"
    print("PROD source:   ", PROD_SERVER)
    print("PREPROD target:", PREPROD_SERVER)
    print("Database:      ", DATABASE_NAME)
    print("Table:         ", f"{schema}.{table}")
    print()

    prod_connection: pyodbc.Connection | None = None
    preprod_connection: pyodbc.Connection | None = None
    try:
        prod_connection = connect(PROD_SERVER, read_only=True)
        preprod_connection = connect(PREPROD_SERVER, read_only=False)
        prod_cursor = prod_connection.cursor()
        preprod_cursor = preprod_connection.cursor()
        if not table_exists(prod_cursor, schema, table):
            raise RuntimeError(f"Source table {schema}.{table} does not exist in PROD")
        if not table_exists(preprod_cursor, schema, table):
            raise RuntimeError(f"Target table {schema}.{table} does not exist in PREPROD")

        prod_columns = fetch_columns(prod_cursor, schema, table)
        if not prod_columns:
            raise RuntimeError(f"Source table {schema}.{table} has no columns in PROD")
        preprod_columns = fetch_columns(preprod_cursor, schema, table)
        expected_rows = row_count(prod_cursor, qualified)
        existing_rows = row_count(preprod_cursor, qualified)
        print(f"PROD rows:    {expected_rows:,}")
        print(f"PREPROD rows: {existing_rows:,}")
        print("Existing PREPROD columns will remain unchanged.")
        preprod_names = {
            str(column["column_name"]).strip().casefold() for column in preprod_columns
        }
        missing_columns = [
            str(column["column_name"])
            for column in prod_columns
            if str(column["column_name"]).strip().casefold() not in preprod_names
        ]
        print("Columns to add: " + (", ".join(missing_columns) if missing_columns else "none"))
        print(
            "PROD columns to synchronize: "
            + ", ".join(str(column["column_name"]) for column in prod_columns)
        )

        expected_confirmation = f"SYNC {schema}.{table}"
        confirmation = input(f"Type '{expected_confirmation}' exactly to continue: ").strip()
        if confirmation != expected_confirmation:
            print("Cancelled; PREPROD was not changed.")
            return

        try:
            # Keep the PREPROD table and its existing structure. DELETE and all
            # subsequent changes are rolled back together if copying fails.
            preprod_cursor.execute(f"DELETE FROM {qualified}")
            added_columns = add_missing_columns(
                preprod_cursor,
                schema,
                table,
                prod_columns,
                preprod_columns,
            )
            refreshed_columns = fetch_columns(preprod_cursor, schema, table)
            copied_rows = copy_rows(
                prod_cursor,
                preprod_cursor,
                qualified,
                prod_columns,
                refreshed_columns,
            )
            actual_rows = row_count(preprod_cursor, qualified)
            if copied_rows != expected_rows or actual_rows != expected_rows:
                raise RuntimeError(
                    "Row-count validation failed: "
                    f"PROD={expected_rows:,}, copied={copied_rows:,}, "
                    f"PREPROD={actual_rows:,}"
                )
            preprod_connection.commit()
        except Exception:
            preprod_connection.rollback()
            raise

        print()
        if added_columns:
            print("Added PREPROD columns: " + ", ".join(added_columns))
        else:
            print("No PREPROD columns needed to be added.")
        print(f"Completed: refreshed {actual_rows:,} PREPROD rows from PROD.")
    finally:
        if prod_connection is not None:
            prod_connection.close()
        if preprod_connection is not None:
            preprod_connection.close()


if __name__ == "__main__":
    main()

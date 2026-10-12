"""Copy one SQL Server table's structure and data from PROD to PREPROD.

Normal usage requires changing only DATABASE_NAME and TABLE_NAME below. The
source connection is opened with ApplicationIntent=ReadOnly. If the target
table already exists, the script requires an explicit replacement confirmation
and performs the PREPROD drop/create/load in one transaction.

It copies columns, data types, lengths, nullability, identity/computed/default
definitions, primary and unique constraints, check constraints, and standard
clustered/nonclustered indexes. It intentionally does not copy permissions,
triggers, foreign keys, partition schemes, or temporal-table configuration.

Requires: pyodbc and Microsoft ODBC Driver 17 for SQL Server.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from typing import Any

import pyodbc


# ---------------------------------------------------------------------------
# Change only these two values for a different database or table.
# TABLE_NAME may be "TableName" (dbo is assumed) or "schema.TableName".
# ---------------------------------------------------------------------------
DATABASE_NAME = "CLMDS_DataModelingAndTextMining"
TABLE_NAME = "dbo.tblFraudThirdPartyAutoBI_GAME"


PROD_SERVER = "clms-prd-sqlmanagedinstance.445cfa5e0fe5.database.windows.net"
PREPROD_SERVER = "clms-preprd-sqlmanagedinstance.3b98dc354c37.database.windows.net"
ODBC_DRIVER = "{ODBC Driver 17 for SQL Server}"
AUTHENTICATION = "ActiveDirectoryInteractive"
BATCH_SIZE = 1_000
CONNECTION_TIMEOUT_SECONDS = 30

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_ $-]*$")


def quote_identifier(value: str) -> str:
    """Quote a validated SQL identifier."""
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"Unsafe SQL identifier: {value!r}")
    return f"[{value.replace(']', ']]')}]"


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


def format_number(value: Any) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def column_definition(column: dict[str, Any]) -> str:
    name = quote_identifier(str(column["column_name"]))
    computed = column["computed_definition"]
    if computed is not None:
        persisted = " PERSISTED" if column["is_persisted"] else ""
        return f"{name} AS {computed}{persisted}"

    if column["generated_always_type"]:
        raise RuntimeError(
            f"Temporal/generated column {column['column_name']!r} requires "
            "special handling and was not copied."
        )

    pieces = [name, sql_type(column)]
    if column["collation_name"]:
        pieces.extend(["COLLATE", str(column["collation_name"])])
    if column["is_sparse"]:
        pieces.append("SPARSE")
    if column["is_rowguidcol"]:
        pieces.append("ROWGUIDCOL")
    if column["seed_value"] is not None:
        pieces.append(
            "IDENTITY"
            f"({format_number(column['seed_value'])},"
            f"{format_number(column['increment_value'])})"
        )
    pieces.append("NULL" if column["is_nullable"] else "NOT NULL")
    if column["default_definition"] is not None:
        pieces.extend(["DEFAULT", str(column["default_definition"])])
    return " ".join(pieces)


def fetch_key_constraints(cursor: pyodbc.Cursor, schema: str, table: str) -> list[dict[str, Any]]:
    cursor.execute(
        """
SELECT
    kc.name AS constraint_name,
    kc.type AS constraint_type,
    i.type_desc,
    ic.key_ordinal,
    c.name AS column_name,
    ic.is_descending_key
FROM sys.tables AS tb
JOIN sys.schemas AS s ON s.schema_id = tb.schema_id
JOIN sys.key_constraints AS kc ON kc.parent_object_id = tb.object_id
JOIN sys.indexes AS i
    ON i.object_id = kc.parent_object_id AND i.index_id = kc.unique_index_id
JOIN sys.index_columns AS ic
    ON ic.object_id = i.object_id AND ic.index_id = i.index_id
JOIN sys.columns AS c
    ON c.object_id = ic.object_id AND c.column_id = ic.column_id
WHERE s.name = ? AND tb.name = ?
ORDER BY kc.name, ic.key_ordinal
""",
        [schema, table],
    )
    names = [description[0] for description in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def fetch_indexes(cursor: pyodbc.Cursor, schema: str, table: str) -> list[dict[str, Any]]:
    cursor.execute(
        """
SELECT
    i.name AS index_name,
    i.is_unique,
    i.type_desc,
    i.has_filter,
    i.filter_definition,
    ic.key_ordinal,
    ic.index_column_id,
    ic.is_included_column,
    ic.is_descending_key,
    c.name AS column_name
FROM sys.tables AS tb
JOIN sys.schemas AS s ON s.schema_id = tb.schema_id
JOIN sys.indexes AS i ON i.object_id = tb.object_id
JOIN sys.index_columns AS ic
    ON ic.object_id = i.object_id AND ic.index_id = i.index_id
JOIN sys.columns AS c
    ON c.object_id = ic.object_id AND c.column_id = ic.column_id
WHERE s.name = ?
  AND tb.name = ?
  AND i.name IS NOT NULL
  AND i.is_primary_key = 0
  AND i.is_unique_constraint = 0
  AND i.is_hypothetical = 0
  AND i.type IN (1, 2)
ORDER BY i.name, ic.is_included_column, ic.key_ordinal, ic.index_column_id
""",
        [schema, table],
    )
    names = [description[0] for description in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def fetch_check_constraints(cursor: pyodbc.Cursor, schema: str, table: str) -> list[dict[str, Any]]:
    cursor.execute(
        """
SELECT cc.name, cc.definition, cc.is_not_for_replication, cc.is_disabled,
       cc.is_not_trusted
FROM sys.tables AS tb
JOIN sys.schemas AS s ON s.schema_id = tb.schema_id
JOIN sys.check_constraints AS cc ON cc.parent_object_id = tb.object_id
WHERE s.name = ? AND tb.name = ?
ORDER BY cc.name
""",
        [schema, table],
    )
    names = [description[0] for description in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def grouped(rows: list[dict[str, Any]], key: str) -> list[list[dict[str, Any]]]:
    groups: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[row[key]].append(row)
    return list(groups.values())


def generated_constraint_name(prefix: str, table: str, ordinal: int) -> str:
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    raw = f"{prefix}_{table}_{stamp}_{ordinal}"
    return raw[:128]


def create_target_table(
    cursor: pyodbc.Cursor,
    schema: str,
    table: str,
    columns: list[dict[str, Any]],
) -> None:
    """Create an empty target and add columns one at a time.

    Individual ALTER statements avoid ambiguous errors from one large CREATE
    TABLE statement and identify the precise source column if SQL Server
    rejects a type or attribute.
    """
    qualified = f"{quote_identifier(schema)}.{quote_identifier(table)}"
    source_names = {str(column["column_name"]).casefold() for column in columns}
    placeholder = "__prod_copy_placeholder__"
    while placeholder.casefold() in source_names:
        placeholder += "_"

    quoted_placeholder = quote_identifier(placeholder)
    cursor.execute(f"CREATE TABLE {qualified} ({quoted_placeholder} bit NULL)")
    for column in columns:
        definition = column_definition(column)
        statement = f"ALTER TABLE {qualified} ADD {definition}"
        try:
            cursor.execute(statement)
        except pyodbc.Error as error:
            raise RuntimeError(
                f"Failed to create column {column['column_name']!r}. " f"Generated SQL: {statement}"
            ) from error
    cursor.execute(f"ALTER TABLE {qualified} DROP COLUMN {quoted_placeholder}")


def create_constraints_and_indexes(
    cursor: pyodbc.Cursor,
    schema: str,
    table: str,
    key_rows: list[dict[str, Any]],
    index_rows: list[dict[str, Any]],
    check_rows: list[dict[str, Any]],
) -> None:
    qualified = f"{quote_identifier(schema)}.{quote_identifier(table)}"

    for ordinal, rows in enumerate(grouped(key_rows, "constraint_name"), start=1):
        first = rows[0]
        kind = "PRIMARY KEY" if first["constraint_type"] == "PK" else "UNIQUE"
        clustered = "CLUSTERED" if first["type_desc"] == "CLUSTERED" else "NONCLUSTERED"
        columns = ", ".join(
            f"{quote_identifier(str(row['column_name']))} "
            f"{'DESC' if row['is_descending_key'] else 'ASC'}"
            for row in rows
        )
        name = generated_constraint_name(kind.replace(" ", "_"), table, ordinal)
        cursor.execute(
            f"ALTER TABLE {qualified} ADD CONSTRAINT {quote_identifier(name)} "
            f"{kind} {clustered} ({columns})"
        )

    for rows in grouped(index_rows, "index_name"):
        first = rows[0]
        key_columns = [row for row in rows if not row["is_included_column"]]
        included_columns = [row for row in rows if row["is_included_column"]]
        columns = ", ".join(
            f"{quote_identifier(str(row['column_name']))} "
            f"{'DESC' if row['is_descending_key'] else 'ASC'}"
            for row in key_columns
        )
        unique = "UNIQUE " if first["is_unique"] else ""
        clustered = "CLUSTERED" if first["type_desc"] == "CLUSTERED" else "NONCLUSTERED"
        statement = (
            f"CREATE {unique}{clustered} INDEX "
            f"{quote_identifier(str(first['index_name']))} ON {qualified} ({columns})"
        )
        if included_columns:
            includes = ", ".join(
                quote_identifier(str(row["column_name"])) for row in included_columns
            )
            statement += f" INCLUDE ({includes})"
        if first["has_filter"]:
            statement += f" WHERE {first['filter_definition']}"
        cursor.execute(statement)

    for ordinal, check in enumerate(check_rows, start=1):
        name = generated_constraint_name("CK", table, ordinal)
        replication = "NOT FOR REPLICATION " if check["is_not_for_replication"] else ""
        validation = "NOCHECK" if check["is_not_trusted"] else "CHECK"
        cursor.execute(
            f"ALTER TABLE {qualified} WITH {validation} ADD CONSTRAINT "
            f"{quote_identifier(name)} CHECK {replication}{check['definition']}"
        )
        if check["is_disabled"]:
            cursor.execute(f"ALTER TABLE {qualified} NOCHECK CONSTRAINT {quote_identifier(name)}")


def source_row_count(cursor: pyodbc.Cursor, qualified_table: str) -> int:
    cursor.execute(f"SELECT COUNT_BIG(*) FROM {qualified_table}")
    return int(cursor.fetchone()[0])


def copy_rows(
    prod_cursor: pyodbc.Cursor,
    preprod_cursor: pyodbc.Cursor,
    qualified_table: str,
    columns: list[dict[str, Any]],
) -> int:
    insertable = [
        column
        for column in columns
        if column["computed_definition"] is None
        and str(column["type_name"]).casefold() not in {"timestamp", "rowversion"}
    ]
    if not insertable:
        return 0

    column_sql = ", ".join(quote_identifier(str(column["column_name"])) for column in insertable)
    placeholders = ", ".join("?" for _ in insertable)
    select_sql = f"SELECT {column_sql} FROM {qualified_table}"
    insert_sql = f"INSERT INTO {qualified_table} ({column_sql}) VALUES ({placeholders})"
    has_identity = any(column["seed_value"] is not None for column in insertable)

    prod_cursor.execute(select_sql)
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

        columns = fetch_columns(prod_cursor, schema, table)
        key_rows = fetch_key_constraints(prod_cursor, schema, table)
        index_rows = fetch_indexes(prod_cursor, schema, table)
        check_rows = fetch_check_constraints(prod_cursor, schema, table)
        expected_rows = source_row_count(prod_cursor, qualified)
        target_exists = table_exists(preprod_cursor, schema, table)

        print(f"PROD contains {len(columns)} columns and {expected_rows:,} rows.")
        if target_exists:
            print(
                "WARNING: The PREPROD target already exists and will be dropped " "and recreated."
            )
            expected_confirmation = f"REPLACE {schema}.{table}"
        else:
            expected_confirmation = f"COPY {schema}.{table}"

        confirmation = input(f"Type '{expected_confirmation}' exactly to continue: ").strip()
        if confirmation != expected_confirmation:
            print("Cancelled; PREPROD was not changed.")
            return

        try:
            if target_exists:
                preprod_cursor.execute(f"DROP TABLE {qualified}")
            create_target_table(preprod_cursor, schema, table, columns)
            copied_rows = copy_rows(prod_cursor, preprod_cursor, qualified, columns)
            create_constraints_and_indexes(
                preprod_cursor,
                schema,
                table,
                key_rows,
                index_rows,
                check_rows,
            )
            actual_rows = source_row_count(preprod_cursor, qualified)
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
        print(
            f"Completed: copied {actual_rows:,} rows and the table structure "
            "from PROD to PREPROD."
        )
    finally:
        if prod_connection is not None:
            prod_connection.close()
        if preprod_connection is not None:
            preprod_connection.close()


if __name__ == "__main__":
    main()

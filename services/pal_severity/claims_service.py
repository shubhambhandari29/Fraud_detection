"""PAL Severity claims table operations."""

import logging
from datetime import datetime
from functools import partial
from typing import Any

from fastapi.concurrency import run_in_threadpool
from fastapi import HTTPException

from core.db_helpers import (
    LAST_UPDATED_BY_COLUMN,
    _get_table_columns,
    _merge_record,
    _quote_identifier,
    _quote_table,
    _validate_record,
    fetch_records_async,
    format_last_updated_by_entry,
    serialize_record_dates,
)
from db import db_connection


logger = logging.getLogger(__name__)
TABLE_NAME = "dbo.tblPALSeverity_OpenClaimsPredictions_Selector_GAME"
PRIMARY_KEY = "ID"
FASTBREAK_TABLE_NAME = "dbo.tblSeverity_Fastbreak_Referral"
FASTBREAK_PRIMARY_KEY = "DERIVE_CLM_FTR_NBR"
FASTBREAK_SOURCE_COLUMNS = (
    "DERIVE_CLM_FTR_NBR",
    "CLM_NBR",
    "CLM_FTR_NBR",
    "FTR_CREAT_DT",
    "CLM_LOB_DESC",
    "FTR_TYPE_DESC",
    "FTR_COVG_TYPE_DESC",
    "ACDNT_ST_ABBR",
    "DT_OF_LOSS",
    "OUTSTANDINGLOSSES",
    "FTR_ASGNED_USER_FIRST_NM",
    "FTR_ASGNED_USER_LAST_NM",
    "FTR_ASGNED_GRP_NM",
)


async def get_claims(
    filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    try:
        records = await fetch_records_async(
            TABLE_NAME,
            filters=filters or None,
            allow_not_equal_filters=True,
        )
        return serialize_record_dates(records)
    except ValueError as error:
        raise HTTPException(status_code=400, detail={"error": str(error)}) from error
    except Exception as error:
        logger.exception("Failed to fetch PAL Severity claims")
        raise HTTPException(
            status_code=500, detail={"error": "Database operation failed"}
        ) from error


def _get_claim_record(cursor: Any, record_id: Any) -> dict[str, Any]:
    cursor.execute(
        f"SELECT * FROM {_quote_table(TABLE_NAME)} "
        f"WHERE {_quote_identifier(PRIMARY_KEY)} = ?",
        [record_id],
    )
    row = cursor.fetchone()
    if row is None:
        return {}
    columns = [description[0] for description in cursor.description]
    return dict(zip(columns, row, strict=True))


def _build_fastbreak_referral(claim: dict[str, Any]) -> dict[str, Any]:
    referral = {column: claim.get(column) for column in FASTBREAK_SOURCE_COLUMNS}
    if not referral[FASTBREAK_PRIMARY_KEY]:
        claim_number = claim.get("CLM_NBR")
        feature_number = claim.get("CLM_FTR_NBR")
        if claim_number is not None and feature_number is not None:
            referral[FASTBREAK_PRIMARY_KEY] = f"{claim_number}-{feature_number}"

    if not referral[FASTBREAK_PRIMARY_KEY]:
        raise ValueError(
            "Fastbreak requires DERIVE_CLM_FTR_NBR or CLM_NBR and CLM_FTR_NBR"
        )

    referral["INSERTDATE"] = datetime.now()
    referral["MODEL"] = "PAL_Severity"
    return referral


def _insert_fastbreak_if_missing(cursor: Any, referral: dict[str, Any]) -> None:
    columns = list(referral)
    column_sql = ", ".join(_quote_identifier(column) for column in columns)
    placeholders = ", ".join("?" for _ in columns)
    key_sql = _quote_identifier(FASTBREAK_PRIMARY_KEY)
    cursor.execute(
        f"IF NOT EXISTS ("
        f"SELECT 1 FROM {_quote_table(FASTBREAK_TABLE_NAME)} WITH (UPDLOCK, HOLDLOCK) "
        f"WHERE {key_sql} = ?"
        f") INSERT INTO {_quote_table(FASTBREAK_TABLE_NAME)} "
        f"({column_sql}) VALUES ({placeholders})",
        [referral[FASTBREAK_PRIMARY_KEY], *[referral[column] for column in columns]],
    )


def upsert_claims_transaction(
    records: list[dict[str, Any]],
    user_id: str,
) -> dict[str, Any]:
    if not records:
        raise ValueError("At least one record is required")

    with db_connection() as connection:
        try:
            cursor = connection.cursor()
            claim_columns = _get_table_columns(cursor, TABLE_NAME)
            referral_columns = _get_table_columns(cursor, FASTBREAK_TABLE_NAME)

            for submitted_record in records:
                record = dict(submitted_record)
                _validate_record(record, claim_columns)
                if PRIMARY_KEY not in record:
                    raise ValueError(f"Missing required upsert key: {PRIMARY_KEY}")

                existing_claim = _get_claim_record(cursor, record[PRIMARY_KEY])
                record[LAST_UPDATED_BY_COLUMN] = (
                    format_last_updated_by_entry(user_id)
                    + str(existing_claim.get(LAST_UPDATED_BY_COLUMN) or "")
                )
                _validate_record(record, claim_columns)
                updated_claim = {**existing_claim, **record}
                _merge_record(
                    cursor,
                    TABLE_NAME,
                    record,
                    PRIMARY_KEY,
                    identity_key=False,
                )

                if str(updated_claim.get("Action") or "").casefold() == "fastbreak":
                    referral = _build_fastbreak_referral(updated_claim)
                    _validate_record(referral, referral_columns)
                    _insert_fastbreak_if_missing(cursor, referral)

            connection.commit()
        except Exception:
            connection.rollback()
            raise

    return {"message": "Upsert successful", "count": len(records)}


async def upsert_claims(
    records: list[dict[str, Any]],
    user_id: str,
) -> dict[str, Any]:
    try:
        return await run_in_threadpool(
            partial(upsert_claims_transaction, records, user_id)
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail={"error": str(error)}) from error
    except Exception as error:
        logger.exception("Failed to upsert PAL Severity claims")
        raise HTTPException(
            status_code=500, detail={"error": "Database operation failed"}
        ) from error

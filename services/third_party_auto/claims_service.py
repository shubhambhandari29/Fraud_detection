"""Third Party Auto claims table operations."""

import logging
from functools import partial
from typing import Any

from fastapi.concurrency import run_in_threadpool
from fastapi import HTTPException

from core.db_helpers import (
    LAST_UPDATED_BY_COLUMN,
    _quote_identifier,
    _quote_table,
    fetch_records_async,
    format_last_updated_by_entry,
    merge_upsert_records_async,
    serialize_record_dates,
)
from db import db_connection


logger = logging.getLogger(__name__)
TABLE_NAME = "dbo.tblFraudThirdPartyAutoBIEDW_OpenClaims_Predictions_Selector"
PRIMARY_KEY = "ID"
CLAIM_NUMBER_COLUMN = "CLM_NBR"
ANALYST_COLUMN = "ANALYST_NAME"
TRANSFER_BATCH_SIZE = 2000


async def get_claims(
    filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    try:
        normalized_filters = dict(filters or {})
        for column, value in list(normalized_filters.items()):
            text_value = str(value)
            if column.casefold() == "status" and text_value.casefold() == "blank":
                normalized_filters[column] = ""
            if column.casefold() == "addressed" and text_value.casefold() in {
                "true",
                "false",
            }:
                normalized_filters[column] = text_value.title()

        records = await fetch_records_async(
            TABLE_NAME,
            filters=normalized_filters or None,
            allow_not_equal_filters=True,
        )
        return serialize_record_dates(records)
    except ValueError as error:
        raise HTTPException(status_code=400, detail={"error": str(error)}) from error
    except Exception as error:
        logger.exception("Failed to fetch claims")
        raise HTTPException(
            status_code=500, detail={"error": "Database operation failed"}
        ) from error


async def upsert_claims(
    records: list[dict[str, Any]],
    user_id: str,
) -> dict[str, Any]:
    try:
        return await merge_upsert_records_async(
            TABLE_NAME,
            records,
            PRIMARY_KEY,
            audit_user_id=user_id,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail={"error": str(error)}) from error
    except Exception as error:
        logger.exception("Failed to upsert claims")
        raise HTTPException(
            status_code=500, detail={"error": "Database operation failed"}
        ) from error


def transfer_claims_transaction(
    target_user: str,
    claim_numbers: list[str],
    user_id: str,
) -> dict[str, Any]:
    unique_claim_numbers = list(dict.fromkeys(claim_numbers))
    if not unique_claim_numbers:
        return {"message": "Claim transfer successful", "count": 0}

    audit_entry = format_last_updated_by_entry(user_id)
    updated_count = 0

    with db_connection() as connection:
        try:
            cursor = connection.cursor()
            for start in range(0, len(unique_claim_numbers), TRANSFER_BATCH_SIZE):
                batch = unique_claim_numbers[start : start + TRANSFER_BATCH_SIZE]
                placeholders = ", ".join("?" for _ in batch)
                cursor.execute(
                    f"UPDATE {_quote_table(TABLE_NAME)} "
                    f"SET {_quote_identifier(ANALYST_COLUMN)} = ?, "
                    f"{_quote_identifier(LAST_UPDATED_BY_COLUMN)} = ? + "
                    f"COALESCE({_quote_identifier(LAST_UPDATED_BY_COLUMN)}, '') "
                    f"OUTPUT inserted.{_quote_identifier(CLAIM_NUMBER_COLUMN)} "
                    f"WHERE {_quote_identifier(CLAIM_NUMBER_COLUMN)} IN ({placeholders})",
                    [target_user, audit_entry, *batch],
                )
                updated_count += len(cursor.fetchall())
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    return {"message": "Claim transfer successful", "count": updated_count}


async def transfer_claims(
    target_user: str,
    claim_numbers: list[str],
    user_id: str,
) -> dict[str, Any]:
    try:
        return await run_in_threadpool(
            partial(
                transfer_claims_transaction,
                target_user,
                claim_numbers,
                user_id,
            )
        )
    except Exception as error:
        logger.exception("Failed to transfer Third Party Auto claims")
        raise HTTPException(
            status_code=500, detail={"error": "Database operation failed"}
        ) from error

"""Claims table operations."""

import logging
from datetime import datetime
from typing import Any

from fastapi import HTTPException

from core.db_helpers import fetch_records_async, merge_upsert_records_async


logger = logging.getLogger(__name__)
TABLE_NAME = "dbo.tblFraudThirdPartyAutoBIEDW_OpenClaims_Predictions_Selector"
PRIMARY_KEY = "ID"
DATE_ADDRESSED_COLUMN = "Date Addressed"


def _format_date_addressed(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for record in records:
        value = record.get(DATE_ADDRESSED_COLUMN)
        if isinstance(value, datetime):
            record[DATE_ADDRESSED_COLUMN] = value.date().isoformat()
    return records


async def get_claims(
    limit: int,
    offset: int,
    status: str | None = None,
    addressed: bool | None = None,
) -> list[dict[str, Any]]:
    try:
        filters: dict[str, Any] = {}
        if status is not None:
            filters["Status"] = "" if status == "Blank" else status
        if addressed is not None:
            filters["Addressed"] = str(addressed)

        records = await fetch_records_async(
            TABLE_NAME,
            limit=limit,
            offset=offset,
            filters=filters or None,
        )
        return _format_date_addressed(records)
    except Exception as error:
        logger.exception("Failed to fetch claims")
        raise HTTPException(
            status_code=500, detail={"error": "Database operation failed"}
        ) from error


async def upsert_claims(records: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        return await merge_upsert_records_async(TABLE_NAME, records, PRIMARY_KEY)
    except ValueError as error:
        raise HTTPException(status_code=400, detail={"error": str(error)}) from error
    except Exception as error:
        logger.exception("Failed to upsert claims")
        raise HTTPException(
            status_code=500, detail={"error": "Database operation failed"}
        ) from error

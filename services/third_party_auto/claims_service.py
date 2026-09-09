"""Third Party Auto claims table operations."""

import logging
from typing import Any

from fastapi import HTTPException

from core.db_helpers import (
    fetch_records_async,
    merge_upsert_records_async,
    serialize_record_dates,
)


logger = logging.getLogger(__name__)
TABLE_NAME = "dbo.tblFraudThirdPartyAutoBIEDW_OpenClaims_Predictions_Selector"
PRIMARY_KEY = "ID"


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
            validate_filters=True,
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

"""ABI Litigation claims table operations."""

import logging
from typing import Any

from fastapi import HTTPException

from core.db_helpers import (
    fetch_records_async,
    merge_upsert_records_async,
    pop_query_parameter,
    serialize_record_dates,
)


logger = logging.getLogger(__name__)
TABLE_NAME = "dbo.tblALLitigation_OpenClaimsPredictions_Selector"
PRIMARY_KEY = "ID"


async def get_claims(
    filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    try:
        normalized_filters = dict(filters or {})
        sort_order = pop_query_parameter(normalized_filters, "Sort_Order")
        records = await fetch_records_async(
            TABLE_NAME,
            filters=normalized_filters or None,
            validate_filters=True,
            allow_not_equal_filters=True,
            sort_order=sort_order,
        )
        return serialize_record_dates(records)
    except ValueError as error:
        raise HTTPException(status_code=400, detail={"error": str(error)}) from error
    except Exception as error:
        logger.exception("Failed to fetch ABI Litigation claims")
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
        logger.exception("Failed to upsert ABI Litigation claims")
        raise HTTPException(
            status_code=500, detail={"error": "Database operation failed"}
        ) from error

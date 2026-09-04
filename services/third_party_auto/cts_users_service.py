"""Third Party Auto CTS user table operations."""

import logging
from typing import Any

from fastapi import HTTPException

from core.db_helpers import (
    fetch_records_async,
    merge_upsert_records_async,
    serialize_record_dates,
)


logger = logging.getLogger(__name__)
TABLE_NAME = "dbo.tblFraudThirdPartyAutoBIEDW_CTS_UserName"
PRIMARY_KEY = "USER_NAME"


async def get_cts_users() -> list[dict[str, Any]]:
    try:
        return serialize_record_dates(await fetch_records_async(TABLE_NAME))
    except Exception as error:
        logger.exception("Failed to fetch CTS users")
        raise HTTPException(
            status_code=500, detail={"error": "Database operation failed"}
        ) from error


async def upsert_cts_users(records: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        return await merge_upsert_records_async(TABLE_NAME, records, PRIMARY_KEY)
    except ValueError as error:
        raise HTTPException(status_code=400, detail={"error": str(error)}) from error
    except Exception as error:
        logger.exception("Failed to upsert CTS users")
        raise HTTPException(
            status_code=500, detail={"error": "Database operation failed"}
        ) from error

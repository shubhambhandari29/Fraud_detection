"""User roster table operations."""

import logging
from typing import Any

from fastapi import HTTPException

from core.db_helpers import fetch_records_async, merge_upsert_records_async


logger = logging.getLogger(__name__)
TABLE_NAME = "dbo.tblFraudThirdPartyAutoBIEDW_Roster"
PRIMARY_KEY = "ID"


async def get_user_roster(limit: int, offset: int) -> list[dict[str, Any]]:
    try:
        return await fetch_records_async(TABLE_NAME, limit=limit, offset=offset)
    except Exception as error:
        logger.exception("Failed to fetch user roster")
        raise HTTPException(
            status_code=500, detail={"error": "Database operation failed"}
        ) from error


async def upsert_user_roster(records: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        return await merge_upsert_records_async(
            TABLE_NAME,
            records,
            PRIMARY_KEY,
            identity_key=True,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail={"error": str(error)}) from error
    except Exception as error:
        logger.exception("Failed to upsert user roster")
        raise HTTPException(
            status_code=500, detail={"error": "Database operation failed"}
        ) from error

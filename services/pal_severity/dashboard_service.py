"""Read-only PAL Severity claim dashboard aggregation."""

import asyncio
import logging
from functools import partial
from typing import Any

from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool
from pyodbc import Cursor

from core.config import settings
from core.db_helpers import serialize_record_dates
from core.models.pal_severity_dashboard import PalSeverityDashboard
from db import db_connection


logger = logging.getLogger(__name__)
EDW_DATE_COLUMNS = {"CLM_RPTD_DT", "FTR_CREAT_DT_U"}

EDW_QUERY = """
SELECT
    [DERIVE_CLM_FTR_NBR],
    [CLM_NBR_U],
    [CLM_FTR_NBR_U],
    [AIA_POSTNS_3_AND_4_DESC],
    [AIA_POSTNS_5_AND_6_DESC],
    [ATTY_REPRSNT_IND],
    [BODY_PART_INJD_DESC],
    [CLM_JRSDTN_ST_DESC],
    [CLM_LOB_DESC],
    [CLM_RPTD_DT],
    [FTR_CREAT_DT_U],
    [COL_DESC_LATEST],
    [LOSS_PARTY],
    [NBR_OF_VEHS_INVLVD_IN_ACDNT_CD],
    [LITIGATION]
FROM [dbo].[tblPALSeverity_EDW_OpenClaims]
WHERE [DERIVE_CLM_FTR_NBR] = ?
"""

CARPE_QUERY = """
SELECT
    [ClientID],
    [ReasonCode],
    [Coverage],
    [ReviewStatus],
    [ImpactSeverity],
    [Notes],
    [URL]
FROM [dbo].[tblCarpeDataWeeklyAlerts]
WHERE [ClientID] = ?
"""


def _fetch_rows(cursor: Cursor, query: str, claim_number: str) -> list[dict[str, Any]]:
    cursor.execute(query, [claim_number])
    columns = [description[0] for description in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def _fetch_edw(claim_number: str) -> list[dict[str, Any]]:
    with db_connection(settings.DATATEXT_DB_NAME) as connection:
        return _fetch_rows(connection.cursor(), EDW_QUERY, claim_number)


def _fetch_carpe(claim_number: str) -> list[dict[str, Any]]:
    with db_connection(settings.VENDOR_DB_NAME, settings.VENDOR_DB_SERVER) as connection:
        return _fetch_rows(connection.cursor(), CARPE_QUERY, claim_number)


async def get_dashboard(claim_number: str) -> PalSeverityDashboard:
    """Return the Power BI claim view for one full claim-feature number."""
    normalized_claim_number = claim_number.strip()
    if not normalized_claim_number:
        raise HTTPException(status_code=400, detail={"error": "Claim number cannot be empty"})

    try:
        edw, carpe = await asyncio.gather(
            run_in_threadpool(partial(_fetch_edw, normalized_claim_number)),
            run_in_threadpool(partial(_fetch_carpe, normalized_claim_number)),
        )
        return PalSeverityDashboard(
            claim_number=normalized_claim_number,
            carpe_available="Y" if carpe else "N",
            edw=serialize_record_dates(edw, date_columns=EDW_DATE_COLUMNS),
            carpe=serialize_record_dates(carpe),
        )
    except HTTPException:
        raise
    except Exception as error:
        logger.exception("Failed to fetch PAL Severity dashboard for claim %s", normalized_claim_number)
        raise HTTPException(
            status_code=500,
            detail={"error": "Database operation failed"},
        ) from error

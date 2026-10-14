"""Read-only ABI Litigation claim dashboard aggregation."""

import logging
from typing import Any

from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool
from pyodbc import Cursor

from core.config import settings
from core.db_helpers import serialize_record_dates
from core.models.abi_litigation_dashboard import AbiLitigationDashboard
from db import db_connection


logger = logging.getLogger(__name__)

EDW_QUERY = """
SELECT
    [DERIVE_CLM_FTR_NBR_U] AS [Claim Feature Number],
    CASE
        WHEN NULLIF(LTRIM(RTRIM([LITGTN_STATUS_DESC])), '') IS NULL
            THEN 'Not in Litigation'
        ELSE [LITGTN_STATUS_DESC]
    END AS [Litigation Status],
    [PDLS_INCL_SLVG_SUBRO_AMT] AS [Paid Amount],
    [CLM_JRSDTN_ST_ABBR] AS [Jurisdiction State],
    CASE
        WHEN NULLIF(REPLACE(LTRIM(RTRIM([LAWSUIT_PRMRY_RSN_DESC])), ' ', ''), '') IS NULL
            THEN 'No info Available'
        ELSE REPLACE(LTRIM(RTRIM([LAWSUIT_PRMRY_RSN_DESC])), ' ', '')
    END AS [Litigation Primary Reason],
    [CAUSE_OF_LOSS] AS [Cause Of Loss],
    [MAJ_PERL_DESC] AS [Major Peril Description]
FROM [dbo].[tblALLitigation_EDW_OpenClaims]
WHERE [DERIVE_CLM_FTR_NBR_U] = ?
"""

GAME_QUERY = """
SELECT
    [DERIVE_CLM_FTR_NBR],
    [Topic],
    [Summary],
    [Game_Run_Date],
    [Word_Length]
FROM [dbo].[tblALLitigation_GAME_REASONS]
WHERE [DERIVE_CLM_FTR_NBR] = ?
  AND [LITIGATION] = 1
  AND [Summary] NOT LIKE '%Error : 400%'
ORDER BY [Game_Run_Date] DESC
"""

LEGACY_GAME_QUERY = """
SELECT
    [DERIVE_CLM_FTR_NBR],
    [Topic],
    [Summary],
    [Game_Run_Date],
    [Word_Length]
FROM [dbo].[tblALLitigation_GAME_REASONS]
WHERE [DERIVE_CLM_FTR_NBR] = ?
  AND [LITIGATION] = 0
  AND [Summary] <> 'Error : 400'
ORDER BY [Game_Run_Date] DESC
"""

_NARRATIVE_FIELDS = {
    "summary of the current status of the claim": "Summary of the Current Status of the Claim",
    "current status of the litigation": "Current Status of the Litigation",
    "next steps in the litigation process": "Next Steps in the Litigation Process",
    "key people involved": "Key People Involved",
    "information not available": "Information Not Available",
    "case investigation": "Case Investigation",
}


def _fetch_rows(cursor: Cursor, query: str, claim_number: str) -> list[dict[str, Any]]:
    """Execute one fixed, parameterized dashboard query."""
    cursor.execute(query, [claim_number])
    columns = [description[0] for description in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def _fetch_dashboard_sections(claim_number: str) -> dict[str, list[dict[str, Any]]]:
    """Load Litigation EDW facts and GAME narratives from the data-text database."""
    with db_connection(settings.DATATEXT_DB_NAME) as connection:
        cursor = connection.cursor()
        return {
            "edw": _fetch_rows(cursor, EDW_QUERY, claim_number),
            "game_rows": _fetch_rows(cursor, GAME_QUERY, claim_number),
            "legacy_game_rows": _fetch_rows(cursor, LEGACY_GAME_QUERY, claim_number),
        }


def _parse_narrative(summary: Any) -> dict[str, str]:
    """Apply the GAME report's `## Heading: value` section parsing."""
    if summary is None:
        return {}

    sections: dict[str, str] = {}
    for section in str(summary).split("## ")[1:]:
        heading, separator, value = section.partition(":")
        if not separator:
            continue
        output_name = _NARRATIVE_FIELDS.get(heading.strip().casefold())
        if output_name is None:
            continue
        cleaned = value.strip()
        if output_name == "Current Status of the Litigation":
            cleaned = cleaned.replace("*", "").strip()
        sections[output_name] = cleaned
    return sections


def _build_game_summaries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return one independently consumable narrative object per GAME source row."""
    summaries: list[dict[str, Any]] = []
    for row in rows:
        parsed = _parse_narrative(row.get("Summary"))
        if not parsed:
            continue
        summaries.append(
            {
                "DERIVE_CLM_FTR_NBR": row.get("DERIVE_CLM_FTR_NBR"),
                "Game_Run_Date": row.get("Game_Run_Date"),
                "Word_Length": row.get("Word_Length"),
                **parsed,
            }
        )
    return summaries


async def get_dashboard(claim_number: str) -> AbiLitigationDashboard:
    """Return the Power BI-equivalent dashboard data for one claim feature."""
    normalized_claim_number = claim_number.strip()
    if not normalized_claim_number:
        raise HTTPException(status_code=400, detail={"error": "Claim number cannot be empty"})

    try:
        sections = await run_in_threadpool(
            _fetch_dashboard_sections,
            normalized_claim_number,
        )
        return AbiLitigationDashboard(
            claim_number=normalized_claim_number,
            edw=serialize_record_dates(sections["edw"]),
            game_summary=serialize_record_dates(
                _build_game_summaries(sections["game_rows"])
            ),
            game_summary_legacy=serialize_record_dates(
                [
                    {
                        **row,
                        "Claim Summary": str(row["Summary"]).replace("*", "").strip()
                        if row.get("Summary") is not None
                        else None,
                    }
                    for row in sections.get("legacy_game_rows", [])
                ]
            ),
        )
    except HTTPException:
        raise
    except Exception as error:
        logger.exception(
            "Failed to fetch ABI Litigation dashboard for claim %s",
            normalized_claim_number,
        )
        raise HTTPException(
            status_code=500,
            detail={"error": "Database operation failed"},
        ) from error

"""Read live selector data without persisting an intermediate table."""

import logging
from collections.abc import Iterable, Sequence
from time import perf_counter
from typing import Any

from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool

from core.models.landing import LandingClaim
from db import db_connection


logger = logging.getLogger(__name__)
MODELS = ("fraud", "litigation", "severity", "subrogation")

# UNION ALL retains every source record. Python groups these rows by claim;
# predictions/actions are never deduplicated or aggregated.
NORMALIZED_ROWS_CTE = """
WITH source_rows AS (
    SELECT N'fraud' AS model,
           CAST([CLM_NBR] AS nvarchar(450)) AS raw_claim_number,
           CAST([ML_PREDICTIONS] AS nvarchar(max)) AS raw_prediction,
           CAST([Status] AS nvarchar(max)) AS raw_action,
           CAST([Feedback] AS nvarchar(max)) AS raw_details
    FROM [dbo].[tblFraudThirdPartyAutoBIEDW_OpenClaims_Predictions_Selector]
    WHERE [Selected] = ?
    UNION ALL
    SELECT N'litigation',
           CAST([DERIVE_CLM_FTR_NBR] AS nvarchar(450)),
           CAST([PREDICTIONS] AS nvarchar(max)),
           CAST([Action] AS nvarchar(max)),
           CAST([ACTION_DETAILS] AS nvarchar(max))
    FROM [dbo].[tblALLitigation_OpenClaimsPredictions_Selector]
    WHERE [Selected] = ?
    UNION ALL
    SELECT N'severity',
           CAST([CLM_NBR] AS nvarchar(450)),
           CAST([PREDICTIONS] AS nvarchar(max)),
           CAST([Action] AS nvarchar(max)),
           CAST([ACTION_DETAILS] AS nvarchar(max))
    FROM [dbo].[tblPALSeverity_OpenClaimsPredictions_Selector_GAME]
    WHERE [Selected] = ?
    UNION ALL
    SELECT N'subrogation',
           CAST([CLM_NBR_U] AS nvarchar(450)),
           CAST([PREDICTIONS] AS nvarchar(max)),
           CAST([Status] AS nvarchar(max)),
           CAST(NULL AS nvarchar(max))
    FROM [dbo].[tblAutoSubro_combinedOpenClaimsPredictions_Selector]
    WHERE [Selected] = ?
), trimmed_rows AS (
    SELECT model,
           LTRIM(RTRIM(raw_claim_number)) AS raw_claim_number,
           LOWER(LTRIM(RTRIM(raw_prediction))) AS raw_prediction,
           NULLIF(LTRIM(RTRIM(raw_action)), N'') AS raw_action,
           NULLIF(LTRIM(RTRIM(raw_details)), N'') AS raw_details
    FROM source_rows
), cleaned_rows AS (
    SELECT model,
           CASE WHEN model = N'litigation' AND raw_claim_number LIKE N'%-%-%'
                THEN SUBSTRING(raw_claim_number, 1,
                     LEN(raw_claim_number) - CHARINDEX(N'-', REVERSE(raw_claim_number)))
                ELSE raw_claim_number END AS claim_number,
           LTRIM(RTRIM(SUBSTRING(raw_prediction,
                 CHARINDEX(N':', raw_prediction) + 1,
                 LEN(raw_prediction)))) AS prediction_label,
           CASE WHEN LOWER(raw_action) = N'null' THEN NULL ELSE raw_action END AS action_text,
           CASE WHEN LOWER(raw_details) = N'null' THEN NULL ELSE raw_details END AS details_text
    FROM trimmed_rows
), normalized_rows AS (
    SELECT model, claim_number,
           CASE prediction_label WHEN N'high' THEN N'High'
                                 WHEN N'low' THEN N'Low'
                                 ELSE NULL END AS [Predictions],
           CASE WHEN action_text IS NULL THEN details_text
                WHEN details_text IS NULL THEN action_text
                ELSE action_text + N' — ' + details_text END AS [Action]
    FROM cleaned_rows
)
"""

# Reference the normalized rows once, with one global sort. This replaces the
# four correlated JSON subqueries per claim and preserves SQL's ordering rules.
LANDING_QUERY = NORMALIZED_ROWS_CTE + """
SELECT model, claim_number, [Predictions], [Action]
FROM normalized_rows
ORDER BY claim_number, model, [Predictions], [Action];
"""


def group_landing_rows(rows: Iterable[Sequence[Any]]) -> list[LandingClaim]:
    """Collect rows in one pass, preserving duplicates and prediction/action pairs."""
    claims: dict[str, dict[str, Any]] = {}
    for model, claim_number, prediction, action in rows:
        if model not in MODELS:
            raise ValueError(f"Unexpected landing model: {model}")
        if claim_number not in claims:
            claims[claim_number] = {
                "claim_number": claim_number,
                **{name: [] for name in MODELS},
            }
        claims[claim_number][model].append({"Predictions": prediction, "Action": action})

    return [LandingClaim.model_validate(claim) for claim in claims.values()]


def fetch_landing_claims() -> list[LandingClaim]:
    started = perf_counter()
    with db_connection() as connection:
        connected = perf_counter()
        cursor = connection.cursor()
        cursor.execute(LANDING_QUERY, [1, 1, 1, 1])
        executed = perf_counter()
        rows = cursor.fetchall()
        fetched = perf_counter()

    closed = perf_counter()
    claims = group_landing_rows(rows)
    finished = perf_counter()
    # Slow requests remain visible even when the application logs only warnings.
    log = logger.warning if finished - started >= 5 else logger.info
    log(
        "Landing claims timings: connection=%.3fs execute=%.3fs fetch=%.3fs "
        "close=%.3fs grouping_validation=%.3fs total=%.3fs rows=%d claims=%d",
        connected - started,
        executed - connected,
        fetched - executed,
        closed - fetched,
        finished - closed,
        finished - started,
        len(rows),
        len(claims),
    )
    return claims


async def get_claims() -> list[LandingClaim]:
    try:
        return await run_in_threadpool(fetch_landing_claims)
    except Exception as error:
        logger.exception("Failed to fetch landing-page claims")
        raise HTTPException(
            status_code=500, detail={"error": "Database operation failed"}
        ) from error

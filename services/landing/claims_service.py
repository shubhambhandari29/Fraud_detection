"""Read live selector data without persisting an intermediate table."""

import json
import logging

from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool

from core.models.landing import LandingClaim
from db import db_connection


logger = logging.getLogger(__name__)
MODELS = ("fraud", "litigation", "severity", "subrogation")

# UNION ALL retains every source record. Only the list of claim numbers is
# deduplicated below; predictions/actions are never deduplicated or aggregated.
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

# Each APPLY returns one JSON array per claim/model, preventing a feature-row
# Cartesian product. INCLUDE_NULL_VALUES distinguishes an empty field from [].
# Returning ordinary SQL rows with JSON columns also avoids the chunking of a
# single large top-level FOR JSON result through ODBC.
LANDING_QUERY = NORMALIZED_ROWS_CTE + """
, claims AS (
    SELECT claim_number FROM normalized_rows GROUP BY claim_number
)
SELECT claims.claim_number,
       fraud.records AS fraud,
       litigation.records AS litigation,
       severity.records AS severity,
       subrogation.records AS subrogation
FROM claims
""" + "\n".join(
    f"""OUTER APPLY (
    SELECT (
        SELECT r.[Predictions], r.[Action]
        FROM normalized_rows AS r
        WHERE r.claim_number = claims.claim_number AND r.model = N'{model}'
        ORDER BY r.[Predictions], r.[Action]
        FOR JSON PATH, INCLUDE_NULL_VALUES
    ) AS records
) AS {model}"""
    for model in MODELS
) + "\nORDER BY claims.claim_number;"


def fetch_landing_claims() -> list[LandingClaim]:
    with db_connection() as connection:
        cursor = connection.cursor()
        cursor.execute(LANDING_QUERY, [1, 1, 1, 1])
        return [
            LandingClaim.model_validate(
                {
                    "claim_number": row[0],
                    **{
                        model: json.loads(row[index])
                        for index, model in enumerate(MODELS, start=1)
                    },
                }
            )
            for row in cursor.fetchall()
        ]


async def get_claims() -> list[LandingClaim]:
    try:
        return await run_in_threadpool(fetch_landing_claims)
    except Exception as error:
        logger.exception("Failed to fetch landing-page claims")
        raise HTTPException(
            status_code=500, detail={"error": "Database operation failed"}
        ) from error

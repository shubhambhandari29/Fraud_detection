"""Read live selector data without persisting an intermediate table."""

import logging
from collections.abc import Iterable, Sequence
from time import perf_counter
from typing import Any

from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool

from core.models.landing import FlatLandingClaim
from db import db_connection


logger = logging.getLogger(__name__)
MODELS = ("fraud", "litigation", "severity", "subrogation")
MODEL_PREFIXES = {
    "fraud": "Fraud",
    "litigation": "Litigation",
    "severity": "Severity",
    "subrogation": "Subrogation",
}

# UI filter mapping and selector-table columns. The landing response uses the
# actual DB column name, except raw Action (Action_Raw) because the existing
# Action key contains combined display text. SQL aliases are model-qualified
# so UNION ALL keeps each filter column's native type distinct.
FILTER_FIELDS: dict[str, tuple[tuple[str, str], ...]] = {
    "fraud": (
        ("referralMechanism", "REFERRAL_MECHANISM"),
        ("ctsStatus", "CTS_TABLE"),
        ("user", "ANALYST_NAME"),
        ("carpeStatus", "CARPE_STATUS"),
        ("lowImpact", "low_apd_pay"),
        ("iesFlag", "IES_FLAG"),
    ),
    "litigation": (
        ("unitManager", "MANAGER_FULL_NM"),
        ("adjuster", "ADJUSTER_FULL_NM"),
        ("action", "Action"),
        ("newUpdates", "New_Updates"),
        ("reviewed", "Addressed"),
        ("predictedByModel", "Litigation_Pred_By_Model"),
        ("reviewedInSeverity", "SEVERITY_REVIEWED"),
    ),
    "severity": (
        ("unitManager", "MANAGER_FULL_NM"),
        ("adjuster", "ADJUSTER_FULL_NM"),
        ("action", "Action"),
        ("newUpdates", "New_Updates"),
        ("reserveThreshold", "Threshold_Filter"),
        ("reserveChange", "Percentage_Bucket"),
    ),
    "subrogation": (
        ("assignActMgr", "ACT_ASGNED_USER_FULL_NM"),
        ("accidentState", "State_Group"),
        ("paymentMade", "PAID_FINAL_IND"),
        ("histSubroGrpAssign", "Subro_hist_flag"),
        ("subjectText", "SUBJ_TXT"),
        ("crrAssignGrpName", "SubroGroup_IND"),
        ("reviewStatus", "Status"),
    ),
}
FILTER_COLUMNS = tuple(
    (model, key, column, f"{model}_{key}")
    for model, fields in FILTER_FIELDS.items()
    for key, column in fields
)
FILTER_POSITIONS = {
    model: tuple(
        ("Action_Raw" if column == "Action" else column, index)
        for index, (source_model, _, column, _) in enumerate(FILTER_COLUMNS)
        if source_model == model
    )
    for model in MODELS
}


def _source_filter_columns(model: str) -> str:
    """Project all filter slots, populating only this model's slots."""
    return ",\n           ".join(
        f"[{column}] AS [{alias}]" if source_model == model else f"NULL AS [{alias}]"
        for source_model, _, column, alias in FILTER_COLUMNS
    )


FILTER_PASS_THROUGH = ",\n           ".join(f"[{alias}]" for _, _, _, alias in FILTER_COLUMNS)

# UNION ALL retains every source record. Python groups these rows by claim;
# predictions/actions are never deduplicated or aggregated.
NORMALIZED_ROWS_CTE = f"""
WITH source_rows AS (
    SELECT N'fraud' AS model,
           CAST([CLM_NBR] AS nvarchar(450)) AS raw_claim_number,
           CASE [SIU_REFERRAL] WHEN 1 THEN N'High'
                               WHEN 0 THEN N'Low'
                               ELSE NULL END AS raw_prediction,
           CAST([Status] AS nvarchar(max)) AS raw_action,
           CAST([Feedback] AS nvarchar(max)) AS raw_details,
           {_source_filter_columns("fraud")}
    FROM [dbo].[tblFraudThirdPartyAutoBIEDW_OpenClaims_Predictions_Selector]
    WHERE [Selected] = ?
    UNION ALL
    SELECT N'litigation',
           CAST([DERIVE_CLM_FTR_NBR] AS nvarchar(450)),
           CAST([PREDICTIONS] AS nvarchar(max)),
           CAST([Action] AS nvarchar(max)),
           CAST([ACTION_DETAILS] AS nvarchar(max)),
           {_source_filter_columns("litigation")}
    FROM [dbo].[tblALLitigation_OpenClaimsPredictions_Selector]
    WHERE [Selected] = ?
    UNION ALL
    SELECT N'severity',
           CAST([CLM_NBR] AS nvarchar(450)),
           CAST([PREDICTIONS] AS nvarchar(max)),
           CAST([Action] AS nvarchar(max)),
           CAST([ACTION_DETAILS] AS nvarchar(max)),
           {_source_filter_columns("severity")}
    FROM [dbo].[tblPALSeverity_OpenClaimsPredictions_Selector_GAME]
    WHERE [Selected] = ?
    UNION ALL
    SELECT N'subrogation',
           CAST([CLM_NBR_U] AS nvarchar(450)),
           CAST([PREDICTIONS] AS nvarchar(max)),
           CAST([Status] AS nvarchar(max)),
           CAST(NULL AS nvarchar(max)),
           {_source_filter_columns("subrogation")}
    FROM [dbo].[tblAutoSubro_combinedOpenClaimsPredictions_Selector]
    WHERE [Selected] = ?
), trimmed_rows AS (
    SELECT model,
           LTRIM(RTRIM(raw_claim_number)) AS raw_claim_number,
           LOWER(LTRIM(RTRIM(raw_prediction))) AS raw_prediction,
           NULLIF(LTRIM(RTRIM(raw_action)), N'') AS raw_action,
           NULLIF(LTRIM(RTRIM(raw_details)), N'') AS raw_details,
           {FILTER_PASS_THROUGH}
    FROM source_rows
), cleaned_rows AS (
    SELECT model,
           CASE WHEN model = N'litigation'
                     AND CHARINDEX(N'-', REVERSE(raw_claim_number)) = 3
                THEN SUBSTRING(raw_claim_number, 1,
                     LEN(raw_claim_number) - CHARINDEX(N'-', REVERSE(raw_claim_number)))
                ELSE raw_claim_number END AS claim_number,
           CASE WHEN model = N'litigation'
                     AND CHARINDEX(N'-', REVERSE(raw_claim_number)) = 3
                THEN SUBSTRING(raw_claim_number, LEN(raw_claim_number) - 1, 2)
                ELSE NULL END AS feature_number,
           LTRIM(RTRIM(SUBSTRING(raw_prediction,
                 CHARINDEX(N':', raw_prediction) + 1,
                 LEN(raw_prediction)))) AS prediction_label,
           CASE WHEN LOWER(raw_action) = N'null' THEN NULL ELSE raw_action END AS action_text,
           CASE WHEN LOWER(raw_details) = N'null' THEN NULL ELSE raw_details END AS details_text,
           {FILTER_PASS_THROUGH}
    FROM trimmed_rows
), normalized_rows AS (
    SELECT model, claim_number, feature_number,
           CASE prediction_label WHEN N'high' THEN N'High'
                                 WHEN N'low' THEN N'Low'
                                 ELSE NULL END AS [Predictions],
           CASE WHEN action_text IS NULL THEN details_text
                WHEN details_text IS NULL THEN action_text
                ELSE action_text + N' — ' + details_text END AS [Action],
           {FILTER_PASS_THROUGH}
    FROM cleaned_rows
)
"""

# Reference the normalized rows once, with one global sort. This replaces the
# four correlated JSON subqueries per claim and preserves SQL's ordering rules.
LANDING_QUERY = NORMALIZED_ROWS_CTE + f"""
SELECT model, claim_number, feature_number, [Predictions], [Action],
       {FILTER_PASS_THROUGH}
FROM normalized_rows
ORDER BY claim_number, model, feature_number, [Predictions], [Action];
"""


def group_landing_rows(rows: Iterable[Sequence[Any]]) -> dict[str, FlatLandingClaim]:
    """Zip each claim's model rows by ordinal into complete, flat records."""
    claims: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for row in rows:
        model, claim_number, feature, prediction, action, *filter_values = row
        if model not in MODELS:
            raise ValueError(f"Unexpected landing model: {model}")
        if len(filter_values) != len(FILTER_COLUMNS):
            raise ValueError("Landing row has an unexpected filter column count")
        if claim_number not in claims:
            claims[claim_number] = {name: [] for name in MODELS}
        recommendation = {
            "Predictions": "High" if prediction == "High" else "Low",
            "Action": action,
        }
        recommendation.update(
            {key: filter_values[index] for key, index in FILTER_POSITIONS[model]}
        )
        if model == "litigation":
            if feature is None:
                raise ValueError("Litigation landing row is missing its feature")
            recommendation["Feature"] = feature
        claims[claim_number][model].append(recommendation)

    result: dict[str, FlatLandingClaim] = {}
    for claim_number, model_rows in claims.items():
        # A numbered key must identify the same source row on repeated requests,
        # including when SQL has tied feature/prediction/action sort values.
        for model in MODELS:
            model_rows[model].sort(key=lambda record: (
                str(record.get("Feature") or ""),
                record["Predictions"] != "High",
                str(record.get("Action") or ""),
                tuple((key, repr(value)) for key, value in sorted(record.items())),
            ))
        count = max(len(model_rows[model]) for model in MODELS)
        for index in range(count):
            flat: dict[str, Any] = {}
            for model in MODELS:
                if index < len(model_rows[model]):
                    flat.update({
                        f"{MODEL_PREFIXES[model]}_{field}": value
                        for field, value in model_rows[model][index].items()
                    })
            key = f"{claim_number}_{index + 1}" if count > 1 else claim_number
            if key in result:
                raise ValueError(f"Duplicate landing response key: {key}")
            result[key] = FlatLandingClaim.model_validate(flat)
    return result


def fetch_landing_claims() -> dict[str, FlatLandingClaim]:
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
        "close=%.3fs grouping_validation=%.3fs total=%.3fs "
        "rows=%d claims=%d entries=%d",
        connected - started,
        executed - connected,
        fetched - executed,
        closed - fetched,
        finished - closed,
        finished - started,
        len(rows),
        len({row[1] for row in rows}),
        len(claims),
    )
    return claims


async def get_claims() -> dict[str, FlatLandingClaim]:
    try:
        return await run_in_threadpool(fetch_landing_claims)
    except Exception as error:
        logger.exception("Failed to fetch landing-page claims")
        raise HTTPException(
            status_code=500, detail={"error": "Database operation failed"}
        ) from error

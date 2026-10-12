"""Read-only Third Party Auto claim dashboard aggregation."""

import asyncio
import logging
from collections.abc import Sequence
from functools import partial
from typing import Any

from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool
from pyodbc import Cursor

from core.config import settings
from core.db_helpers import serialize_record_dates
from core.models.third_party_auto_dashboard import (
    DashboardIndicators,
    ThirdPartyAutoDashboard,
)
from db import db_connection


logger = logging.getLogger(__name__)

EDW_QUERY = """
SELECT
    LEFT([DERIVE_CLM_FTR_NBR_U], 11) AS [Clm_Nbr],
    [CLM_FTR_NBR],
    [CLMNT_FULL_NM],
    [FTR_CREAT_DT_U],
    [TM_OF_LOSS],
    [NBR_OF_VEHS_INVLVD_IN_ACDNT_CD],
    [ATTY_REPRSNT_IND],
    [BODY_PART_INJD_DESC],
    [LOSS_PARTY],
    [CLM_JRSDTN_ST_ABBR],
    [COL_CD],
    [ACDNT_WITNS_IND],
    [AIA_POSTNS_1_AND_2_CD],
    [COMN_COVG_DESC],
    [EMPLYMT_STATUS_CD],
    [INJRY_TYPE_DESC],
    [INSRD_FAULT_PCTG],
    [VEH_MILEAGE_CNT],
    [ISO_match_found]
FROM [dbo].[tblFraudAutoDashboardEDW]
WHERE LEFT([DERIVE_CLM_FTR_NBR_U], 11) = ?
ORDER BY [BODY_PART_INJD_DESC] ASC
"""

CTS_QUERY = """
SELECT
    [CaseID],
    [CauseType],
    [CaseType],
    [InvestigationType],
    [NICBReferral],
    [NICBInvolvement],
    [PolicyNumber],
    [RiskState],
    [ReferralStatus],
    [InvestigatorName],
    [AssignmentDate],
    [ReferredToLawEnf],
    [ResultStatus]
FROM [dbo].[tblCTSClaimCase]
WHERE [HCSClaimNumber] = ?
"""

SMART_FEATURES_QUERY = """
SELECT
    [AutoScoreID],
    [Base],
    [Geo],
    [Lossfreq],
    [Intelli],
    [LossAddr],
    [Addbase],
    [Enthist],
    [MailAddr],
    [Vinhist],
    [bodily],
    [Losstime]
FROM [dbo].[tblVeriskAutoScore]
WHERE LEFT([CLM_NBR], 2) + '-' + RIGHT([CLM_NBR], LEN([CLM_NBR]) - 2) = ?
ORDER BY [AutoScoreID] ASC
"""

WATCHLIST_QUERY = """
SELECT
    [ID],
    [SIU_ALERT_DESC],
    [POL_IND],
    [PRDCR_IND],
    [INDIV_IND],
    [ADDR_IND],
    [VENDR_IND],
    [VENDR_NM],
    [Check_IND]
FROM [dbo].[tblFraudThirdPartyAutoBIEDW_SIU_ALL_ALERTS_OUTPUT]
WHERE [CLM_NBR] = ?
ORDER BY [VENDR_IND] DESC
"""

IES_BILLS_QUERY = """
SELECT
    [Claim Adjuster],
    [Demand Package Number],
    [Patient Age],
    [Claim Number],
    [Service Provider],
    [Treatment State],
    [Bill ID],
    [Bill Line],
    [Procedure Code],
    [Medical Reason Code],
    [Service Recieve Date],
    [Provider Specialty],
    [Submitted $],
    [Accepted $],
    [Financial Impact]
FROM [dbo].[tblFraud_Auto_BI_3P_IES_bills_report]
WHERE [Claim Number] = ?
"""

IES_FLAGS_QUERY = """
SELECT
    [Demand Package Number],
    [Bill ID],
    [Bill Line],
    [Flag Short Name],
    [Flag Type Code],
    [Procedure Category],
    [Procedure Sub Category]
FROM [dbo].[tblFraud_Auto_BI_3P_IES_flags_report]
WHERE [Claim Number] = ?
"""

ALERT_REASONS_QUERY = """
SELECT [alert_reason_concat]
FROM [dbo].[tblFraudThirdPartyAutoBIEDW_OpenClaims_AlertReasons]
WHERE [CLM_NBR] = ?
"""

CARPE_QUERY = """
SELECT
    [ClientID],
    [ReasonCode],
    [Coverage],
    [ReviewStatus],
    [ImpactSeverity],
    [Notes],
    [URL],
    [DateRun]
FROM [dbo].[tblCarpeDataWeeklyAlerts]
WHERE LEFT([ClientID], 11) = ?
ORDER BY [ReviewStatus] ASC
"""

GAME_SUMMARY_QUERY = """
SELECT [clm_nbr], [topic], [value], [template]
FROM [dbo].[tblFraudThirdPartyAutoBI_GAME]
WHERE [clm_nbr] = ?
"""


def _fetch_rows(cursor: Cursor, query: str, claim_number: str) -> list[dict[str, Any]]:
    """Execute one fixed, parameterized dashboard query."""
    cursor.execute(query, [claim_number])
    columns = [description[0] for description in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def _fetch_fraud_sections(claim_number: str) -> dict[str, list[dict[str, Any]]]:
    """Load all dashboard sections stored in CLMAA_FraudModel."""
    with db_connection(settings.FRAUD_DB_NAME) as connection:
        cursor = connection.cursor()
        return {
            "edw": _fetch_rows(cursor, EDW_QUERY, claim_number),
            "cts": _fetch_rows(cursor, CTS_QUERY, claim_number),
            "smart_features": _fetch_rows(cursor, SMART_FEATURES_QUERY, claim_number),
            "watchlist": _fetch_rows(cursor, WATCHLIST_QUERY, claim_number),
            "ies_bills": _fetch_rows(cursor, IES_BILLS_QUERY, claim_number),
            "ies_flags": _fetch_rows(cursor, IES_FLAGS_QUERY, claim_number),
            "alert_reason_rows": _fetch_rows(cursor, ALERT_REASONS_QUERY, claim_number),
        }


def _fetch_vendor_sections(claim_number: str) -> dict[str, list[dict[str, Any]]]:
    """Load the Carpe section stored in CLM_VendorData."""
    with db_connection(settings.VENDOR_DB_NAME) as connection:
        return {"carpe": _fetch_rows(connection.cursor(), CARPE_QUERY, claim_number)}


def _fetch_datatext_sections(
    claim_number: str,
) -> dict[str, list[dict[str, Any]]]:
    """Load the GAME narrative stored in DataModelingAndTextMining."""
    with db_connection(settings.DATATEXT_DB_NAME) as connection:
        return {"game_summary": _fetch_rows(connection.cursor(), GAME_SUMMARY_QUERY, claim_number)}


def _nonblank_unique(values: Sequence[Any]) -> list[Any]:
    """Return unique, nonblank values while preserving database order."""
    result: list[Any] = []
    for value in values:
        if value is None or value == "" or value in result:
            continue
        result.append(value)
    return result


def _ies_key(row: dict[str, Any]) -> tuple[Any, Any, Any]:
    return tuple(
        "" if value is None else str(value)
        for value in (
            row.get("Demand Package Number"),
            row.get("Bill ID"),
            row.get("Bill Line"),
        )
    )


def _attach_ies_flags(
    bills: list[dict[str, Any]], flags: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Attach every matching flag without multiplying the bill rows."""
    flags_by_bill: dict[tuple[Any, Any, Any], list[dict[str, Any]]] = {}
    for flag in flags:
        flags_by_bill.setdefault(_ies_key(flag), []).append(flag)

    enriched_bills: list[dict[str, Any]] = []
    for bill in bills:
        enriched = dict(bill)
        matching_flags = flags_by_bill.get(_ies_key(bill), [])
        enriched["Flag Short Names"] = ";".join(
            str(value)
            for value in _nonblank_unique([flag.get("Flag Short Name") for flag in matching_flags])
        )
        enriched["Flag Type Codes"] = ";".join(
            str(value)
            for value in _nonblank_unique([flag.get("Flag Type Code") for flag in matching_flags])
        )
        enriched["Flags"] = matching_flags
        enriched_bills.append(enriched)
    return enriched_bills


def _split_alert_reasons(rows: list[dict[str, Any]]) -> list[str]:
    reasons: list[str] = []
    for row in rows:
        value = row.get("alert_reason_concat")
        if value is None:
            continue
        for reason in str(value).split(";"):
            cleaned = reason.strip()
            if cleaned and cleaned not in reasons:
                reasons.append(cleaned)
    return reasons


def _yes_no(condition: bool) -> str:
    return "Y" if condition else "N"


def _iso_match(edw_rows: list[dict[str, Any]]) -> str:
    values = _nonblank_unique([row.get("ISO_match_found") for row in edw_rows])
    return _yes_no(
        any(str(value).strip().casefold() in {"y", "yes", "true", "1"} for value in values)
    )


def _build_indicators(
    *,
    edw: list[dict[str, Any]],
    cts: list[dict[str, Any]],
    smart_features: list[dict[str, Any]],
    watchlist: list[dict[str, Any]],
    carpe: list[dict[str, Any]],
    ies_bills: list[dict[str, Any]],
) -> DashboardIndicators:
    assigned = any(
        str(row.get("ReferralStatus", "")).strip().casefold() == "investigator assigned"
        for row in cts
    )
    dcw_statuses = {"compromised", "denied", "withdrawn"}
    dcw = any(str(row.get("ResultStatus", "")).strip().casefold() in dcw_statuses for row in cts)
    return DashboardIndicators(
        assigned=_yes_no(assigned),
        dcw=_yes_no(dcw),
        cts=_yes_no(bool(cts)),
        smart_features=_yes_no(bool(smart_features)),
        watchlist=_yes_no(bool(watchlist)),
        carpe=_yes_no(bool(carpe)),
        ies_bills=_yes_no(bool(ies_bills)),
        iso_match=_iso_match(edw),
    )


async def get_dashboard(claim_number: str) -> ThirdPartyAutoDashboard:
    """Return the Power BI-equivalent dashboard data for one claim."""
    normalized_claim_number = claim_number.strip()
    if not normalized_claim_number:
        raise HTTPException(status_code=400, detail={"error": "Claim number cannot be empty"})

    try:
        fraud, vendor, datatext = await asyncio.gather(
            run_in_threadpool(partial(_fetch_fraud_sections, normalized_claim_number)),
            run_in_threadpool(partial(_fetch_vendor_sections, normalized_claim_number)),
            run_in_threadpool(partial(_fetch_datatext_sections, normalized_claim_number)),
        )

        edw = serialize_record_dates(fraud["edw"])
        cts = serialize_record_dates(fraud["cts"])
        smart_features = serialize_record_dates(fraud["smart_features"])
        watchlist = serialize_record_dates(fraud["watchlist"])
        carpe = serialize_record_dates(vendor["carpe"])
        bills = serialize_record_dates(fraud["ies_bills"])
        flags = serialize_record_dates(fraud["ies_flags"])
        ies_bills = _attach_ies_flags(bills, flags)
        game_summary = serialize_record_dates(datatext["game_summary"])

        return ThirdPartyAutoDashboard(
            claim_number=normalized_claim_number,
            indicators=_build_indicators(
                edw=edw,
                cts=cts,
                smart_features=smart_features,
                watchlist=watchlist,
                carpe=carpe,
                ies_bills=ies_bills,
            ),
            edw=edw,
            cts=cts,
            smart_features=smart_features,
            watchlist=watchlist,
            carpe=carpe,
            ies_bills=ies_bills,
            alert_reasons=_split_alert_reasons(fraud["alert_reason_rows"]),
            game_summary=game_summary,
        )
    except HTTPException:
        raise
    except Exception as error:
        logger.exception(
            "Failed to fetch Third Party Auto dashboard for claim %s",
            normalized_claim_number,
        )
        raise HTTPException(
            status_code=500, detail={"error": "Database operation failed"}
        ) from error

"""Read-only data for the ABI Litigation Law Firm Profiling report."""

import logging
from datetime import date, datetime
from typing import Any

from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool
from pyodbc import Cursor

from core.config import settings
from core.db_helpers import serialize_record_dates
from core.models.abi_litigation_law_firm_dashboard import LawFirmDashboard, LawFirmKpis
from db import db_connection
from services.dashboard_placeholders import empty_section_or_placeholder


logger = logging.getLogger(__name__)
MATTER_DATE_COLUMNS = {
    "FTR_CREAT_DT_U",
    "FTR_CLOSE_DT_U",
    "CLM_RPTD_DT_U",
    "CLM_CLOSE_DT_U",
    "LGL_MATTER_OPEN_DT",
    "LAWSUIT_CLOSE_DT",
}

MATTERS_QUERY = """
SELECT
    [PLNTF_ATTY_LAW_FIRM_NM],
    [CLM_NBR_U],
    [CLM_FTR_NBR_U],
    [DERIVE_CLM_FTR_NBR_U],
    [MATTER_HCS_SYS_ID],
    [FTR_CREAT_DT_U],
    [FTR_CLOSE_DT_U],
    [CLM_RPTD_DT_U],
    [CLM_CLOSE_DT_U],
    [LGL_MATTER_OPEN_DT],
    [LAWSUIT_CLOSE_DT],
    [LAWSUIT_CASE_NBR],
    [ATTY_ACTVTY_RESLTN_DESC],
    [LAWSUIT_FINL_STTLMT_AMT],
    [CLM_JRSDTN_ST_ABBR],
    [HCS_POL_LOB_DESC],
    [Feature_PIP_Indicator]
FROM [dbo].[vw_plaintiff_lawfirm_data_v2]
WHERE [PLNTF_ATTY_LAW_FIRM_NM] = ?
"""

NOTES_QUERY = """
SELECT [PLNTF_ATTY_LAW_FIRM_NM], [Category], [Note_Chunk]
FROM [dbo].[vw_lawfirm_profile_v2]
WHERE [PLNTF_ATTY_LAW_FIRM_NM] = ?
ORDER BY CASE WHEN [Category] = 'Full Summary' THEN 1 ELSE 2 END, [Category]
"""

SETTLEMENT_RESOLUTIONS = (
    "Settled - Arbitration",
    "Settled - Mediation",
    "Settled Pre-Trial Conference",
    "Settled at Appeal",
    "Settled at Trial",
    "Settled during Discovery",
)

TRIAL_RESOLUTIONS = (
    "Appeal - Decision for Defendant",
    "Appeal - Decision for Plaintiff",
    "Trial - Verdict for Defendant",
    "Trial - Verdict for Plaintiff",
)


def _fetch_rows(cursor: Cursor, query: str, law_firm_name: str) -> list[dict[str, Any]]:
    cursor.execute(query, [law_firm_name])
    columns = [description[0] for description in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def _fetch_law_firm_sections(law_firm_name: str) -> dict[str, list[dict[str, Any]]]:
    with db_connection(settings.DATATEXT_DB_NAME) as connection:
        cursor = connection.cursor()
        return {
            "claim_info": _fetch_rows(cursor, MATTERS_QUERY, law_firm_name),
            "notes": _fetch_rows(cursor, NOTES_QUERY, law_firm_name),
        }


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        try:
            return datetime.fromisoformat(stripped).date()
        except ValueError:
            pass
        for date_format in (
            "%Y-%m-%d",
            "%Y-%m-%d %H:%M:%S",
            "%m/%d/%Y",
            "%m/%d/%Y %H:%M:%S",
        ):
            try:
                return datetime.strptime(stripped, date_format).date()
            except ValueError:
                continue
    return None


def _average_days(pairs: list[tuple[date, date]]) -> float | None:
    if not pairs:
        return None
    return sum((end - start).days for start, end in pairs) / len(pairs)


def _build_kpis(rows: list[dict[str, Any]]) -> LawFirmKpis:
    matter_ids = {row["MATTER_HCS_SYS_ID"] for row in rows if row.get("MATTER_HCS_SYS_ID") is not None}
    claim_ids = {row["CLM_NBR_U"] for row in rows if row.get("CLM_NBR_U") is not None}
    closed_ids = {
        row["MATTER_HCS_SYS_ID"]
        for row in rows
        if row.get("MATTER_HCS_SYS_ID") is not None and row.get("LAWSUIT_CLOSE_DT")
    }
    open_ids = matter_ids - closed_ids
    settled_ids: set[Any] = set()
    trial_ids: set[Any] = set()
    litigation_durations: list[tuple[date, date]] = []
    claim_dates: set[tuple[Any, date, date]] = set()

    for row in rows:
        matter_id = row.get("MATTER_HCS_SYS_ID")
        resolution = str(row.get("ATTY_ACTVTY_RESLTN_DESC") or "").casefold()
        if matter_id is not None:
            if any(value.casefold() in resolution for value in SETTLEMENT_RESOLUTIONS):
                settled_ids.add(matter_id)
            if any(value.casefold() in resolution for value in TRIAL_RESOLUTIONS):
                trial_ids.add(matter_id)
        opened = _as_date(row.get("LGL_MATTER_OPEN_DT"))
        closed = _as_date(row.get("LAWSUIT_CLOSE_DT"))
        if opened and closed:
            litigation_durations.append((opened, closed))
        reported = _as_date(row.get("CLM_RPTD_DT_U"))
        claim_closed = _as_date(row.get("CLM_CLOSE_DT_U"))
        if row.get("CLM_NBR_U") is not None and reported and claim_closed:
            claim_dates.add((row["CLM_NBR_U"], reported, claim_closed))

    count = len(matter_ids)
    return LawFirmKpis(
        claim_count=len(claim_ids),
        legal_matter_count=count,
        legal_matter_open_count=len(open_ids),
        settlement_percentage=len(settled_ids) / count * 100 if count else 0,
        trial_percentage=len(trial_ids) / count * 100 if count else 0,
        litigation_open_percentage=len(open_ids) / count * 100 if count else 0,
        litigation_duration_days=_average_days(litigation_durations),
        claim_duration_days=_average_days(
            [(reported, closed) for _, reported, closed in claim_dates]
        ),
    )


def _settlement_bin(value: Any) -> str:
    if value is None or value == "":
        return "NA"
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return "NA"
    if amount < 1_000:
        return "<$1K"
    if amount < 10_000:
        return "$1K-$10K"
    if amount < 50_000:
        return "$10K-$50K"
    if amount < 100_000:
        return "$50K-$100K"
    if amount < 250_000:
        return "$100K-$250K"
    return ">$250K"


def _count_by(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    groups: dict[str, set[Any]] = {}
    for row in rows:
        value = row.get(key)
        matter_id = row.get("MATTER_HCS_SYS_ID")
        if value is None or matter_id is None:
            continue
        groups.setdefault(str(value), set()).add(matter_id)
    return [
        {"value": value, "count": len(matter_ids)}
        for value, matter_ids in sorted(groups.items())
    ]


def _settlement_bins(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    order = ("NA", "<$1K", "$1K-$10K", "$10K-$50K", "$50K-$100K", "$100K-$250K", ">$250K")
    groups: dict[str, set[Any]] = {value: set() for value in order}
    for row in rows:
        matter_id = row.get("MATTER_HCS_SYS_ID")
        if matter_id is not None:
            groups[_settlement_bin(row.get("LAWSUIT_FINL_STTLMT_AMT"))].add(matter_id)
    return [{"value": value, "count": len(groups[value])} for value in order]


def _annual_rates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    years: dict[int, dict[str, set[Any]]] = {}
    for row in rows:
        reported = _as_date(row.get("CLM_RPTD_DT_U"))
        matter_id = row.get("MATTER_HCS_SYS_ID")
        if reported is None or matter_id is None:
            continue
        group = years.setdefault(reported.year, {"all": set(), "settled": set(), "trial": set()})
        group["all"].add(matter_id)
        resolution = str(row.get("ATTY_ACTVTY_RESLTN_DESC") or "").casefold()
        if any(value.casefold() in resolution for value in SETTLEMENT_RESOLUTIONS):
            group["settled"].add(matter_id)
        if any(value.casefold() in resolution for value in TRIAL_RESOLUTIONS):
            group["trial"].add(matter_id)
    return [
        {
            "year": year,
            "settlement_percentage": len(group["settled"]) / len(group["all"]) * 100,
            "trial_percentage": len(group["trial"]) / len(group["all"]) * 100,
        }
        for year, group in sorted(years.items())
    ]


async def get_law_firm_dashboard(law_firm_name: str) -> LawFirmDashboard:
    normalized_name = law_firm_name.strip()
    if not normalized_name:
        raise HTTPException(status_code=400, detail={"error": "Law firm name cannot be empty"})

    try:
        sections = await run_in_threadpool(_fetch_law_firm_sections, normalized_name)
        rows = sections["claim_info"]
        return LawFirmDashboard(
            law_firm_name=normalized_name,
            kpis=_build_kpis(rows),
            claim_info=serialize_record_dates(rows, date_columns=MATTER_DATE_COLUMNS),
            notes=empty_section_or_placeholder(
                serialize_record_dates(sections["notes"]), "law_firm.notes", normalized_name
            ),
            resolution_counts=_count_by(rows, "ATTY_ACTVTY_RESLTN_DESC"),
            settlement_bins=_settlement_bins(rows),
            line_of_business_counts=_count_by(rows, "HCS_POL_LOB_DESC"),
            jurisdiction_counts=_count_by(rows, "CLM_JRSDTN_ST_ABBR"),
            annual_rates=empty_section_or_placeholder(
                _annual_rates(rows), "law_firm.annual_rates", normalized_name
            ),
        )
    except HTTPException:
        raise
    except Exception as error:
        logger.exception("Failed to fetch ABI Litigation law firm dashboard for %s", normalized_name)
        raise HTTPException(status_code=500, detail={"error": "Database operation failed"}) from error

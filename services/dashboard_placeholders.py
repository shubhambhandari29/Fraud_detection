"""Temporary, response-only Power BI dashboard fixtures for UI development.

Remove this module and its callers when the source tables have usable test data.
Set DASHBOARD_PLACEHOLDERS_ENABLED=false to disable the fixtures without a code change.
"""

from typing import Any

from core.config import settings


def empty_section_or_placeholder(
    rows: list[dict[str, Any]], section: str, subject: str
) -> list[dict[str, Any]]:
    """Preserve real rows; substitute one visibly synthetic row only when empty."""
    if rows or not settings.DASHBOARD_PLACEHOLDERS_ENABLED:
        return rows

    label = "DEVELOPMENT PLACEHOLDER"
    fixtures: dict[str, dict[str, Any]] = {
        "fraud.edw": {
            "Clm_Nbr": subject,
            "CLM_FTR_NBR": "01",
            "CLMNT_FULL_NM": f"{label} CLAIMANT",
            "FTR_CREAT_DT_U": "2026-01-15",
            "TM_OF_LOSS": "10:30:00",
            "NBR_OF_VEHS_INVLVD_IN_ACDNT_CD": 2,
            "ATTY_REPRSNT_IND": "N",
            "BODY_PART_INJD_DESC": f"{label}: body part",
            "LOSS_PARTY": "third_party",
            "CLM_JRSDTN_ST_ABBR": "MI",
            "COL_CD": "auto",
            "ACDNT_WITNS_IND": "N",
            "AIA_POSTNS_1_AND_2_CD": None,
            "COMN_COVG_DESC": "Bodily Injury",
            "EMPLYMT_STATUS_CD": None,
            "INJRY_TYPE_DESC": "Soft tissue",
            "INSRD_FAULT_PCTG": 50,
            "VEH_MILEAGE_CNT": 25000,
            "ISO_match_found": "N",
        },
        "fraud.watchlist": {
            "ID": -1,
            "SIU_ALERT_DESC": f"{label}: sample SIU alert",
            "POL_IND": False,
            "PRDCR_IND": False,
            "INDIV_IND": False,
            "ADDR_IND": False,
            "VENDR_IND": True,
            "VENDR_NM": f"{label} VENDOR",
            "Check_IND": False,
        },
        "fraud.ies_bills": {
            "Claim Adjuster": f"{label} ADJUSTER",
            "Demand Package Number": "DEV-DP-001",
            "Patient Age": 35,
            "Claim Number": subject,
            "Service Provider": f"{label} PROVIDER",
            "Treatment State": "MI",
            "Bill ID": "DEV-BILL-001",
            "Bill Line": 1,
            "Procedure Code": "99213",
            "Medical Reason Code": "DEV",
            "Service Recieve Date": "2026-01-16",
            "Provider Specialty": "General Practice",
            "Submitted $": 250.00,
            "Accepted $": 200.00,
            "Financial Impact": 50.00,
            "Flag Short Names": f"{label} FLAG",
            "Flag Type Codes": "DEV",
            "Flags": [
                {
                    "Demand Package Number": "DEV-DP-001",
                    "Bill ID": "DEV-BILL-001",
                    "Bill Line": 1,
                    "Flag Short Name": f"{label} FLAG",
                    "Flag Type Code": "DEV",
                    "Procedure Category": "Medical",
                    "Procedure Sub Category": "Office Visit",
                    "_dummy": True,
                }
            ],
        },
        "litigation.game_summary": {
            "DERIVE_CLM_FTR_NBR": subject,
            "Game_Run_Date": None,
            "Word_Length": 0,
            "Summary of the Current Status of the Claim": f"{label}: claim status narrative.",
            "Current Status of the Litigation": f"{label}: litigation status narrative.",
            "Next Steps in the Litigation Process": f"{label}: next steps narrative.",
            "Key People Involved": f"{label}: people narrative.",
            "Information Not Available": f"{label}: missing information narrative.",
            "Case Investigation": f"{label}: investigation narrative.",
        },
        "law_firm.notes": {
            "PLNTF_ATTY_LAW_FIRM_NM": subject,
            "Category": "Full Summary",
            "Note_Chunk": f"{label}: sample law firm profile narrative.",
        },
        "law_firm.annual_rates": {
            "year": 2025,
            "settlement_percentage": 40.0,
            "trial_percentage": 10.0,
        },
    }
    return [{**fixtures[section], "_dummy": True}]

"""Flat, model-qualified claim summaries for the combined landing page."""

from typing import Any, Literal

from pydantic import BaseModel


class FlatLandingClaim(BaseModel):
    """One ordinal row across the four models for a normalized claim number."""

    Fraud_Predictions: Literal["High", "Low"] = "Low"
    Fraud_Action: str | None = None
    Fraud_REFERRAL_MECHANISM: Any = None
    Fraud_CTS_TABLE: Any = None
    Fraud_ANALYST_NAME: Any = None
    Fraud_CARPE_STATUS: Any = None
    Fraud_low_apd_pay: Any = None
    Fraud_IES_FLAG: Any = None

    Litigation_Predictions: Literal["High", "Low"] = "Low"
    Litigation_Action: str | None = None
    Litigation_Feature: str | None = None
    Litigation_MANAGER_FULL_NM: Any = None
    Litigation_ADJUSTER_FULL_NM: Any = None
    Litigation_Action_Raw: Any = None
    Litigation_New_Updates: Any = None
    Litigation_Addressed: Any = None
    Litigation_Litigation_Pred_By_Model: Any = None
    Litigation_SEVERITY_REVIEWED: Any = None

    Severity_Predictions: Literal["High", "Low"] = "Low"
    Severity_Action: str | None = None
    Severity_MANAGER_FULL_NM: Any = None
    Severity_ADJUSTER_FULL_NM: Any = None
    Severity_Action_Raw: Any = None
    Severity_New_Updates: Any = None
    Severity_Threshold_Filter: Any = None
    Severity_Percentage_Bucket: Any = None

    Subrogation_Predictions: Literal["High", "Low"] = "Low"
    Subrogation_Action: str | None = None
    Subrogation_ACT_ASGNED_USER_FULL_NM: Any = None
    Subrogation_State_Group: Any = None
    Subrogation_PAID_FINAL_IND: Any = None
    Subrogation_Subro_hist_flag: Any = None
    Subrogation_SUBJ_TXT: Any = None
    Subrogation_SubroGroup_IND: Any = None
    Subrogation_Status: Any = None

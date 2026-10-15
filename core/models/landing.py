"""Claim summaries for the combined model landing page."""

from typing import Any, Literal

from pydantic import BaseModel


class ModelRecommendation(BaseModel):
    Predictions: Literal["High", "Low"] | None
    Action: str | None


class FraudRecommendation(ModelRecommendation):
    REFERRAL_MECHANISM: Any = None
    CTS_TABLE: Any = None
    ANALYST_NAME: Any = None
    CARPE_STATUS: Any = None
    low_apd_pay: Any = None
    IES_FLAG: Any = None


class LitigationRecommendation(ModelRecommendation):
    Feature: str
    MANAGER_FULL_NM: Any = None
    ADJUSTER_FULL_NM: Any = None
    Action_Raw: Any = None
    New_Updates: Any = None
    Addressed: Any = None
    Litigation_Pred_By_Model: Any = None
    SEVERITY_REVIEWED: Any = None


class SeverityRecommendation(ModelRecommendation):
    MANAGER_FULL_NM: Any = None
    ADJUSTER_FULL_NM: Any = None
    Action_Raw: Any = None
    New_Updates: Any = None
    Threshold_Filter: Any = None
    Percentage_Bucket: Any = None


class SubrogationRecommendation(ModelRecommendation):
    ACT_ASGNED_USER_FULL_NM: Any = None
    State_Group: Any = None
    PAID_FINAL_IND: Any = None
    Subro_hist_flag: Any = None
    SUBJ_TXT: Any = None
    SubroGroup_IND: Any = None
    Status: Any = None


class LandingClaim(BaseModel):
    claim_number: str
    fraud: list[FraudRecommendation]
    litigation: list[LitigationRecommendation]
    severity: list[SeverityRecommendation]
    subrogation: list[SubrogationRecommendation]

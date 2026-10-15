"""Claim summaries for the combined model landing page."""

from typing import Any, Literal

from pydantic import BaseModel


class ModelRecommendation(BaseModel):
    Predictions: Literal["High", "Low"] | None
    Action: str | None


class FraudRecommendation(ModelRecommendation):
    referralMechanism: Any = None
    ctsStatus: Any = None
    user: Any = None
    carpeStatus: Any = None
    lowImpact: Any = None
    iesFlag: Any = None


class LitigationRecommendation(ModelRecommendation):
    Feature: str
    unitManager: Any = None
    adjuster: Any = None
    action: Any = None
    newUpdates: Any = None
    reviewed: Any = None
    predictedByModel: Any = None
    reviewedInSeverity: Any = None


class SeverityRecommendation(ModelRecommendation):
    unitManager: Any = None
    adjuster: Any = None
    action: Any = None
    newUpdates: Any = None
    reserveThreshold: Any = None
    reserveChange: Any = None


class SubrogationRecommendation(ModelRecommendation):
    assignActMgr: Any = None
    accidentState: Any = None
    paymentMade: Any = None
    histSubroGrpAssign: Any = None
    subjectText: Any = None
    crrAssignGrpName: Any = None
    reviewStatus: Any = None


class LandingClaim(BaseModel):
    claim_number: str
    fraud: list[FraudRecommendation]
    litigation: list[LitigationRecommendation]
    severity: list[SeverityRecommendation]
    subrogation: list[SubrogationRecommendation]

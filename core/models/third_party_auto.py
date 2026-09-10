"""Third Party Auto API request models."""

from pydantic import BaseModel


class ClaimTransferRequest(BaseModel):
    target_user: str
    claim_numbers: list[str]

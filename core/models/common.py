"""Shared API request and response models."""

from typing import Any

from pydantic import BaseModel, Field


class UpsertRequest(BaseModel):
    records: list[dict[str, Any]] = Field(min_length=1)


class WriteResult(BaseModel):
    message: str
    count: int

"""Shared API request and response models."""

from pydantic import BaseModel


class WriteResult(BaseModel):
    message: str
    count: int

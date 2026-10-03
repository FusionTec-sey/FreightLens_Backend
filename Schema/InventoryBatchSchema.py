"""Explicit lot identity, supplied by a trusted receiving/opening adapter."""
from datetime import date
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator


class StockBatchIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)
    batch_key: UUID
    code: str = Field(min_length=1, max_length=100)
    shade: str | None = Field(default=None, min_length=1, max_length=80)
    calibre: str | None = Field(default=None, min_length=1, max_length=80)
    expires_on: date | None = None

    @field_validator("batch_key")
    @classmethod
    def nonzero_key(cls, value):
        if not value.int:
            raise ValueError("A nonzero batch key is required")
        return value

"""Typed requests and reads for reviewed below-floor sales pricing."""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PriceFloorCaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    operation_key: UUID
    document_key: UUID
    expected_draft_version: int = Field(gt=0, strict=True)
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("operation_key", "document_key")
    @classmethod
    def nonzero(cls, value, info):
        if not value.int:
            raise ValueError(f"{info.field_name.replace('_', ' ').title()} must be nonzero")
        return value


class PriceFloorCaseRead(BaseModel):
    case_key: UUID
    version: int
    status: Literal["REQUESTED", "APPROVED", "REJECTED", "CONSUMED"]
    document_key: UUID
    draft_version: int
    currency: Literal["SCR"] = "SCR"
    gross_total_scr: str
    floor_line_count: int
    pricing_fingerprint: str
    reason: str
    requestor_id: int
    reviewer_id: int | None
    review_reason: str | None
    requested_at: datetime

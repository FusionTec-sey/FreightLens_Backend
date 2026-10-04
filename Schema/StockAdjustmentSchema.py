"""Exact reviewed location-stock adjustment API contracts."""
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StockAdjustmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    operation_key: UUID
    balance_id: int = Field(gt=0, strict=True)
    expected_source_version: int = Field(gt=0, strict=True)
    target_on_hand: Decimal
    target_damaged: Decimal = Decimal("0")
    target_quarantined: Decimal = Decimal("0")
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("operation_key")
    @classmethod
    def nonzero(cls, value):
        if not value.int:
            raise ValueError("Operation key must be nonzero")
        return value


class StockAdjustmentExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_key: UUID

    @field_validator("operation_key")
    @classmethod
    def nonzero(cls, value):
        if not value.int:
            raise ValueError("Operation key must be nonzero")
        return value


class StockAdjustmentCaseRead(BaseModel):
    case_key: UUID
    version: int
    status: Literal["REQUESTED", "APPROVED", "REJECTED", "CONSUMED"]
    balance_id: int
    branch_id: int
    location_id: int
    product_id: int
    product_name: str
    base_unit: str
    tracking_policy: Literal["UNTRACKED", "BATCH"]
    batch_key: UUID | None
    source_version: int
    before_on_hand: str
    reserved: str
    before_damaged: str
    before_quarantined: str
    target_on_hand: str
    target_damaged: str
    target_quarantined: str
    reason: str
    requestor_id: int
    reviewer_id: int | None
    review_reason: str | None
    requested_at: datetime


class StockAdjustmentExecutionRead(BaseModel):
    operation_key: UUID
    case_key: UUID
    status: Literal["CONSUMED"]
    balance_id: int
    version: int
    on_hand: str
    reserved: str
    available: str
    damaged: str
    quarantined: str
    replayed: bool


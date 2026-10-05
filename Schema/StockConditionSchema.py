"""Reviewed exact T18 return-stock condition transition contracts."""
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StockConditionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    operation_key: UUID
    credit_note_line_id: int = Field(gt=0, strict=True)
    expected_source_version: int = Field(gt=0, strict=True)
    quantity: Decimal
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("operation_key")
    @classmethod
    def nonzero(cls, value):
        if not value.int:
            raise ValueError("Operation key must be nonzero")
        return value

    @field_validator("quantity", mode="before")
    @classmethod
    def exact_positive_quantity(cls, value):
        if isinstance(value, float):
            raise ValueError("Quantity must not use binary floating point")
        value = Decimal(value) if isinstance(value, (str, int)) and not isinstance(value, bool) else value
        if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
            raise ValueError("Quantity must be a positive exact decimal")
        if value != value.quantize(Decimal("0.000001")):
            raise ValueError("Quantity has more than six decimal places")
        return value


class StockConditionExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_key: UUID

    @field_validator("operation_key")
    @classmethod
    def nonzero(cls, value):
        if not value.int:
            raise ValueError("Operation key must be nonzero")
        return value


class StockConditionCaseRead(BaseModel):
    case_key: UUID
    version: int
    status: Literal["REQUESTED", "APPROVED", "REJECTED", "CONSUMED"]
    credit_note_line_id: int
    credit_note_key: UUID
    credit_note_number: str
    return_key: UUID
    return_operation_key: UUID
    invoice_key: UUID
    invoice_line_key: UUID
    handover_allocation_key: UUID
    balance_id: int
    branch_id: int
    branch_name: str
    location_id: int
    location_name: str
    product_id: int
    product_name: str
    product_sku: str
    base_unit: str
    tracking_policy: Literal["UNTRACKED", "BATCH"]
    batch_key: UUID | None
    source_version: int
    quantity: str
    source_return_quantity: str
    previously_transitioned: str
    pending_review_quantity: str
    from_condition: Literal["QUARANTINED"]
    to_condition: Literal["DAMAGED"]
    before_on_hand: str
    before_reserved: str
    before_damaged: str
    before_quarantined: str
    target_damaged: str
    target_quarantined: str
    reason: str
    requestor_id: int
    reviewer_id: int | None
    review_reason: str | None
    requested_at: datetime


class StockConditionExecutionRead(BaseModel):
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
    condition_effect: Literal["QUARANTINED_TO_DAMAGED"] = "QUARANTINED_TO_DAMAGED"
    valuation_effect: Literal["NONE"] = "NONE"
    accounting_effect: Literal["NONE"] = "NONE"
    pricing_effect: Literal["NONE"] = "NONE"


class StockConditionSourceRead(BaseModel):
    credit_note_line_id: int
    credit_note_key: UUID
    credit_note_number: str
    return_key: UUID
    return_operation_key: UUID
    invoice_key: UUID
    invoice_line_key: UUID
    handover_allocation_key: UUID
    branch_id: int
    branch_name: str
    location_id: int
    location_name: str
    product_id: int
    product_name: str
    product_sku: str
    base_unit: str
    tracking_policy: Literal["UNTRACKED", "BATCH"]
    batch_key: UUID | None
    source_quantity: str
    previously_transitioned: str
    pending_review_quantity: str
    remaining_eligible: str
    quarantined_available: str
    stock_version: int

"""Reviewed immutable inventory-cost reconciliation contracts."""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CostReconciliationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    operation_key: UUID
    cost_pool_id: int = Field(gt=0, strict=True)
    product_id: int = Field(gt=0, strict=True)
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("operation_key")
    @classmethod
    def nonzero(cls, value):
        if not value.int:
            raise ValueError("Operation key must be nonzero")
        return value


class CostReconciliationExecute(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_key: UUID

    @field_validator("operation_key")
    @classmethod
    def nonzero(cls, value):
        if not value.int:
            raise ValueError("Operation key must be nonzero")
        return value


class CostReconciliationCaseRead(BaseModel):
    case_key: UUID
    version: int
    status: Literal["REQUESTED", "APPROVED", "REJECTED", "CONSUMED"]
    cost_pool_id: int
    product_id: int
    product_name: str
    valuation_id: int
    valuation_version: int
    base_unit: str
    pool_quantity: str
    pool_value_scr: str
    balance_count: int
    reason: str
    requestor_id: int
    reviewer_id: int | None = None
    review_reason: str | None = None
    requested_at: datetime


class CostReconciliationRead(BaseModel):
    checkpoint_key: UUID
    cost_pool_id: int
    product_id: int
    product_name: str
    valuation_id: int
    valuation_version: int
    base_unit: str
    pool_quantity: str
    pool_value_scr: str
    line_count: int
    status: Literal["CLOSED"]
    created_at: datetime
    created_by: int


class CostReconciliationExecutionRead(BaseModel):
    operation_key: UUID
    checkpoint_key: UUID
    case_key: UUID
    status: Literal["CLOSED"]
    cost_pool_id: int
    product_id: int
    valuation_id: int
    valuation_version: int
    pool_quantity: str
    pool_value_scr: str
    replayed: bool

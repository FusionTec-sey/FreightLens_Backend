"""Reviewed opening/import intent; no legacy product-total fields."""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from Schema.InventoryBatchSchema import StockBatchIdentity
from Schema.InventorySerialSchema import SerialOpening


QUANTITY = r'^[0-9]{1,12}(?:\.[0-9]{1,6})?$'
MONEY = r'^[0-9]{1,18}(?:\.[0-9]{1,6})?$'


class InventoryOpeningInput(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True,
        str_strip_whitespace=True)
    source_key: UUID
    branch_id: int = Field(gt=0, strict=True)
    location_id: int = Field(gt=0, strict=True)
    product_id: int = Field(gt=0, strict=True)
    expected_policy_version: int = Field(gt=0, strict=True)
    expected_valuation_version: int = Field(ge=0, strict=True)
    on_hand: str = Field(pattern=QUANTITY)
    damaged: str = Field(pattern=QUANTITY)
    quarantined: str = Field(pattern=QUANTITY)
    goods_value_scr: str = Field(pattern=MONEY)
    additional_cost_scr: str = Field(pattern=MONEY)
    reason: str = Field(min_length=1, max_length=500)
    batch: StockBatchIdentity | None = None
    serials: SerialOpening | None = None

    @field_validator('source_key')
    @classmethod
    def nonzero_source(cls, value):
        if not value.int:
            raise ValueError('Opening source key must be nonzero')
        return value


class InventoryOpeningRequest(InventoryOpeningInput):
    operation_key: UUID

    @field_validator('operation_key')
    @classmethod
    def nonzero_operation(cls, value):
        if not value.int:
            raise ValueError('Operation key must be nonzero')
        return value


class InventoryOpeningExecute(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    operation_key: UUID

    @field_validator('operation_key')
    @classmethod
    def nonzero_operation(cls, value):
        if not value.int:
            raise ValueError('Operation key must be nonzero')
        return value


class InventoryOpeningCaseRead(BaseModel):
    case_key: UUID
    version: int
    status: Literal['REQUESTED', 'APPROVED', 'REJECTED', 'CONSUMED']
    reason: str
    requestor_id: int
    reviewer_id: int | None = None
    review_reason: str | None = None
    requested_at: datetime
    source_key: UUID
    branch_id: int
    location_id: int
    product_id: int
    product_name: str
    base_unit: str
    tracking_policy: Literal['UNTRACKED', 'BATCH', 'SERIAL']
    expected_policy_version: int
    expected_valuation_version: int
    on_hand: str
    damaged: str
    quarantined: str
    goods_value_scr: str
    additional_cost_scr: str


class InventoryOpeningExecutionRead(BaseModel):
    operation_key: UUID
    case_key: UUID
    replayed: bool
    status: Literal['POSTED_UNRECONCILED']
    balance_id: int
    balance_version: int
    valuation_id: int
    valuation_version: int
    cost_pool_id: int
    product_id: int
    on_hand: str
    available: str
    damaged: str
    quarantined: str
    pool_quantity: str
    pool_value_scr: str
    average_cost_scr: str

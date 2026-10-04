from datetime import datetime
from typing import Literal
from pydantic import BaseModel
from pydantic import ConfigDict, Field, StrictInt, field_validator
from decimal import Decimal
from Services.inventory_costing_service import MAX_VALUE


class InventoryValuationRead(BaseModel):
    id: int
    kind: Literal['OPENING', 'RECEIPT', 'CHARGE'] = 'OPENING'
    source_valuation_id: int | None = None
    product_id: int
    product_name: str
    balance_id: int
    source_version: int
    version: int
    base_unit: str
    quantity: str
    goods_value_scr: str
    additional_cost_scr: str
    pool_quantity: str
    pool_value_scr: str
    status: Literal['UNRECONCILED']
    reason: str
    created_at: datetime


class InventoryReconciliationRead(BaseModel):
    product_id: int
    product_name: str
    physical_base_units: list[str]
    physical_quantity: str | None
    valuation_id: int | None
    valuation_version: int | None
    valuation_base_unit: str | None
    pool_quantity: str | None
    pool_value_scr: str | None
    difference: str | None
    readiness: Literal['READY', 'MISSING_VALUATION', 'QUANTITY_MISMATCH',
        'UNIT_MISMATCH']


class CostAllocationPreviewRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    valuation_ids: list[StrictInt] = Field(min_length=1, max_length=100)
    total_scr: str
    basis: Literal['GOODS_VALUE', 'BASE_QUANTITY']

    @field_validator('valuation_ids')
    @classmethod
    def unique_sources(cls, value):
        if any(item <= 0 for item in value) or len(set(value)) != len(value):
            raise ValueError('Select distinct positive valuation IDs')
        return value

    @field_validator('total_scr')
    @classmethod
    def exact_total(cls, value):
        import re
        if not re.fullmatch(r'[0-9]{1,18}(?:\.[0-9]{1,6})?', value) or Decimal(value) > MAX_VALUE:
            raise ValueError('Enter a nonnegative SCR amount with up to six decimal places')
        return value


class CostAllocationLine(BaseModel):
    valuation_id: int
    balance_id: int
    product_id: int
    product_name: str
    base_unit: str
    basis_value: str
    allocated_scr: str


class CostAllocationPreview(BaseModel):
    currency: Literal['SCR'] = 'SCR'
    posting_enabled: Literal[False] = False
    basis: Literal['GOODS_VALUE', 'BASE_QUANTITY']
    total_scr: str
    lines: list[CostAllocationLine]

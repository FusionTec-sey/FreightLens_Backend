"""Sales demand, not an invoice, payment, reservation or collection entitlement."""
from decimal import Decimal
from uuid import UUID
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SalesIntentLineInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    line_key: UUID
    product_id: int = Field(gt=0, strict=True)
    expected_policy_version: int = Field(gt=0, strict=True)
    quantity: str = Field(max_length=25, pattern=r'^[0-9]{1,12}(?:\.[0-9]{1,6})?$')
    unit: str = Field(min_length=1, max_length=50)

    @field_validator('quantity')
    @classmethod
    def positive_quantity(cls, value):
        if Decimal(value) <= 0:
            raise ValueError('Requested quantity must be positive')
        return value

    @field_validator('line_key')
    @classmethod
    def nonzero_key(cls, value):
        if value.int == 0:
            raise ValueError('A nonzero stable line identity is required')
        return value


class SalesIntentInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    customer_key: UUID
    expected_customer_version: int = Field(ge=1, le=1, strict=True)
    branch_id: int = Field(gt=0, strict=True)
    lines: list[SalesIntentLineInput] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def unique_lines(self):
        if len({line.line_key for line in self.lines}) != len(self.lines):
            raise ValueError('Every draft line needs a unique stable identity')
        return self


class SalesIntentSave(BaseModel):
    model_config = ConfigDict(extra='forbid')
    operation_key: UUID
    expected_version: int = Field(ge=0, strict=True)
    draft: SalesIntentInput


class SalesIntentSaved(BaseModel):
    document_key: UUID
    version: int
    status: Literal['DRAFT']
    replayed: bool


class SalesIntentLineRead(SalesIntentLineInput):
    base_quantity: str
    base_unit: str
    product_name: str | None
    sku: str | None
    units: list[str]
    reserved_quantity: str


class SalesIntentRead(SalesIntentInput):
    document_key: UUID
    version: int
    status: Literal['DRAFT']
    lines: list[SalesIntentLineRead]


class SalesIntentSummary(BaseModel):
    document_key: UUID
    version: int
    status: Literal['DRAFT']
    customer_key: UUID
    branch_id: int

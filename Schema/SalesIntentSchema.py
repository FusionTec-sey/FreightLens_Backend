"""Sales demand, not an invoice, payment, reservation or collection entitlement."""
from decimal import Decimal
from datetime import datetime
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
    expected_customer_version: int = Field(ge=1, strict=True)
    branch_id: int = Field(gt=0, strict=True)
    lines: list[SalesIntentLineInput] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def unique_lines(self):
        if len({line.line_key for line in self.lines}) != len(self.lines):
            raise ValueError('Every draft line needs a unique stable identity')
        return self


class SalesIntentSourceReference(BaseModel):
    model_config = ConfigDict(extra='forbid')
    document_key: UUID
    version: int = Field(ge=1, strict=True)

    @field_validator('document_key')
    @classmethod
    def nonzero_document_key(cls, value):
        if value.int == 0:
            raise ValueError('A nonzero source document identity is required')
        return value


class SalesIntentSave(BaseModel):
    model_config = ConfigDict(extra='forbid')
    operation_key: UUID
    expected_version: int = Field(ge=0, strict=True)
    draft: SalesIntentInput
    source_reference: SalesIntentSourceReference | None = None

    @model_validator(mode='after')
    def copy_reference_is_initial_only(self):
        if self.source_reference is not None and self.expected_version != 0:
            raise ValueError('A source reference is allowed only on the initial draft save')
        return self


class SalesIntentSaved(BaseModel):
    document_key: UUID
    version: int
    status: Literal['DRAFT']
    replayed: bool
    search_indexed: bool = False


class SalesIntentHistoricalLine(SalesIntentLineInput):
    image_signed_url: str | None = None
    base_quantity: str
    base_unit: str
    product_name: str | None
    sku: str | None
    units: list[str]


class SalesIntentLineRead(SalesIntentHistoricalLine):
    reserved_quantity: str


class SalesIntentRead(SalesIntentInput):
    customer_name: str | None = None
    branch_name: str | None = None
    created_at: datetime
    created_by: int
    document_key: UUID
    version: int
    status: Literal['DRAFT']
    source_reference: SalesIntentSourceReference | None = None
    lines: list[SalesIntentLineRead]


class SalesIntentSummary(BaseModel):
    customer_name: str | None = None
    document_key: UUID
    version: int
    status: Literal['DRAFT']
    customer_key: UUID
    branch_id: int
    branch_name: str | None = None


class SalesIntentHistoryItem(BaseModel):
    document_key: UUID
    version: int
    status: Literal['DRAFT']
    customer_key: UUID
    customer_version: int
    customer_name: str | None = None
    branch_id: int
    created_at: datetime
    created_by: int


class SalesIntentHistoryDetail(SalesIntentHistoryItem):
    branch_name: str | None = None
    source_reference: SalesIntentSourceReference | None = None
    lines: list[SalesIntentHistoricalLine]
    read_only: Literal[True] = True
    catalogue_labels_current: Literal[True] = True

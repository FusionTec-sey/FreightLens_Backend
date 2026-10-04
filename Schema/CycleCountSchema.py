"""Cycle-count contracts (T33A). A count record is never a stock adjustment.

The blind projections here are the enforcement point, not a UI convention: the
counter-facing models have no field for expected stock, earlier rounds or value,
so a serialisation mistake cannot leak one.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

QUANTITY = r'^[0-9]{1,12}(?:\.[0-9]{1,6})?$'


def _nonzero(value: UUID) -> UUID:
    if not value.int:
        raise ValueError('A nonzero stable identity is required')
    return value


class CountPlanCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    operation_key: UUID
    branch_id: int = Field(gt=0, strict=True)
    code: str = Field(min_length=1, max_length=32, pattern=r'^[A-Z0-9][A-Z0-9_-]{0,31}$')
    name: str = Field(min_length=1, max_length=160)
    year: int = Field(ge=2000, le=2100, strict=True)

    @field_validator('operation_key')
    @classmethod
    def nonzero_key(cls, value):
        return _nonzero(value)

    @field_validator('code', mode='before')
    @classmethod
    def normalise_code(cls, value):
        return value.strip().upper() if isinstance(value, str) else value


class CountScopeLine(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    product_id: int = Field(gt=0)
    location_id: int = Field(gt=0)
    cadence: Literal['ANNUAL', 'QUARTERLY', 'MONTHLY'] = 'ANNUAL'
    due_on: date


class CountScopeSave(BaseModel):
    model_config = ConfigDict(extra='forbid')
    operation_key: UUID
    expected_state: Literal['DRAFT'] = 'DRAFT'
    lines: list[CountScopeLine] = Field(min_length=1, max_length=500)

    @model_validator(mode='after')
    def unique_lines(self):
        keys = [(line.product_id, line.location_id) for line in self.lines]
        if len(keys) != len(set(keys)):
            raise ValueError('Each product and location may appear once in a plan')
        return self


class CountPlanActivate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    operation_key: UUID
    expected_state: Literal['DRAFT'] = 'DRAFT'


class CountPlanRead(BaseModel):
    plan_key: UUID
    id: int
    branch_id: int
    branch_name: str | None = None
    code: str
    name: str
    year: int
    state: Literal['DRAFT', 'ACTIVE', 'CLOSED']
    scope_lines: int = 0
    created_at: datetime | None = None


class CountCoverageRow(BaseModel):
    location_id: int
    location_name: str | None = None
    scope_lines: int
    counted_lines: int
    outstanding_lines: int
    next_due_on: date | None = None


class CountSessionCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    operation_key: UUID
    plan_key: UUID
    location_id: int = Field(gt=0, strict=True)
    assignee_id: int = Field(gt=0, strict=True)


class CountSessionRead(BaseModel):
    session_key: UUID
    id: int
    plan_key: UUID
    plan_code: str | None = None
    branch_id: int
    location_id: int
    location_name: str | None = None
    assignee_id: int
    assignee_name: str | None = None
    state: Literal['ASSIGNED', 'IN_PROGRESS', 'SUBMITTED', 'REVIEWED', 'CANCELLED']
    round: int
    expected_lines: int = 0
    entered_lines: int = 0
    submitted_at: datetime | None = None


class BlindSheetLine(BaseModel):
    """What a counter may see: identity, unit and step. Nothing else."""
    product_id: int
    product_name: str | None = None
    sku: str | None = None
    location_id: int
    location_name: str | None = None
    base_unit: str
    quantity_step: str
    units: list[str]
    entered: bool = False


class BlindSheetRead(BaseModel):
    session_key: UUID
    state: Literal['ASSIGNED', 'IN_PROGRESS', 'SUBMITTED', 'REVIEWED', 'CANCELLED']
    round: int
    location_id: int
    location_name: str | None = None
    lines: list[BlindSheetLine]


class CountEntryInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    product_id: int = Field(gt=0, strict=True)
    location_id: int = Field(gt=0, strict=True)
    quantity: str = Field(max_length=25, pattern=QUANTITY)
    unit: str = Field(min_length=1, max_length=50)

    @field_validator('quantity')
    @classmethod
    def countable(cls, value):
        # Zero is a legitimate count: the shelf was empty.
        if Decimal(value) < 0:
            raise ValueError('A counted quantity cannot be negative')
        return value


class CountEntrySave(BaseModel):
    model_config = ConfigDict(extra='forbid')
    operation_key: UUID
    entries: list[CountEntryInput] = Field(min_length=1, max_length=200)

    @model_validator(mode='after')
    def unique_entries(self):
        keys = [(entry.product_id, entry.location_id) for entry in self.entries]
        if len(keys) != len(set(keys)):
            raise ValueError('Each product and location may be counted once per round')
        return self


class CountEntrySaved(BaseModel):
    session_key: UUID
    entered_lines: int
    state: Literal['IN_PROGRESS']
    replayed: bool = False


class CountSubmit(BaseModel):
    model_config = ConfigDict(extra='forbid')
    operation_key: UUID
    expected_entered_lines: int = Field(ge=1, strict=True)


class CountSubmitted(BaseModel):
    session_key: UUID
    state: Literal['SUBMITTED']
    discrepancy_lines: int
    replayed: bool = False


class CountRecount(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    operation_key: UUID
    assignee_id: int = Field(gt=0, strict=True)
    reason: str = Field(min_length=1, max_length=1000)


class DiscrepancyRead(BaseModel):
    id: int
    session_key: UUID
    round: int
    product_id: int
    product_name: str | None = None
    sku: str | None = None
    location_id: int
    location_name: str | None = None
    counted_base: str
    expected_base: str
    difference_base: str
    base_unit: str
    state: Literal['PROVISIONAL', 'REVIEWED']
    outcome: Literal['ACCEPTED', 'RECOUNT_REQUIRED', 'REJECTED'] | None = None
    case_key: UUID | None = None


class DiscrepancyReviewRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    operation_key: UUID
    expected_counted_base: str = Field(max_length=25, pattern=QUANTITY)
    reason: str = Field(min_length=1, max_length=1000)


class DiscrepancyDecision(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    operation_key: UUID
    case_key: UUID
    expected_version: Literal[1] = 1
    outcome: Literal['ACCEPTED', 'RECOUNT_REQUIRED', 'REJECTED']
    reason: str = Field(min_length=1, max_length=1000)


class DiscrepancyDecided(BaseModel):
    discrepancy_id: int
    outcome: Literal['ACCEPTED', 'RECOUNT_REQUIRED', 'REJECTED']
    state: Literal['REVIEWED']
    replayed: bool = False

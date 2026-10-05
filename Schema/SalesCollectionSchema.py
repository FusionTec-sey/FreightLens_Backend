"""Strict API contracts for invoice-bound partial collection."""
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _nonzero(value: UUID) -> UUID:
    if value.int == 0:
        raise ValueError("UUID must be nonzero")
    return value


class SalesCollectionAllocationInput(BaseModel):
    """One exact committed reservation quantity requested for handover."""

    model_config = ConfigDict(extra="forbid")
    line_key: UUID
    reservation_key: UUID
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    expected_stock_version: int = Field(gt=0)
    serial_keys: list[UUID] = Field(default_factory=list, max_length=500)

    @field_validator("line_key", "reservation_key")
    @classmethod
    def valid_key(cls, value: UUID) -> UUID:
        return _nonzero(value)

    @field_validator("quantity", mode="before")
    @classmethod
    def exact_quantity(cls, value):
        if isinstance(value, float):
            raise ValueError("Collection quantity must be an exact decimal string")
        quantity = value if isinstance(value, Decimal) else Decimal(value)
        if not quantity.is_finite() or quantity <= 0:
            raise ValueError("Collection quantity must be positive")
        return quantity

    @field_validator("serial_keys")
    @classmethod
    def unique_serial_keys(cls, values: list[UUID]) -> list[UUID]:
        if any(not value.int for value in values):
            raise ValueError("Serial UUID must be nonzero")
        if len(set(values)) != len(values):
            raise ValueError("A serial identity may appear only once per allocation")
        return values


class SalesCollectionCreate(BaseModel):
    """One stable collection command against current branch/counter authority."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    collection_key: UUID
    operation_key: UUID
    invoice_key: UUID
    branch_id: int = Field(gt=0)
    counter_key: UUID
    expected_branch_settings_version: int = Field(gt=0)
    expected_counter_settings_version: int = Field(gt=0)
    expected_assignment_version: int = Field(gt=0)
    collector_name: str = Field(min_length=1, max_length=150)
    collector_contact: str = Field(min_length=1, max_length=50)
    allocations: list[SalesCollectionAllocationInput] = Field(min_length=1, max_length=500)

    @field_validator("collection_key", "operation_key", "invoice_key", "counter_key")
    @classmethod
    def valid_key(cls, value: UUID) -> UUID:
        return _nonzero(value)

    @model_validator(mode="after")
    def unique_reservations(self):
        pairs = [(item.line_key, item.reservation_key) for item in self.allocations]
        if len(set(pairs)) != len(pairs):
            raise ValueError("A line reservation may appear only once per collection")
        return self


class SalesCollectionCounterOption(BaseModel):
    counter_key: UUID
    code: str
    name: str
    version: int


class SalesCollectionLineOption(BaseModel):
    line_key: UUID
    product_id: int
    product_name: str
    sku: str
    base_quantity: str
    collected: str
    remaining: str
    base_unit: str


class SalesCollectionSerialOption(BaseModel):
    serial_key: UUID
    serial_number: str


class SalesCollectionReservationOption(BaseModel):
    line_key: UUID
    reservation_key: UUID
    branch_id: int
    balance_id: int
    location_id: int
    location_code: str
    location_name: str
    tracking_policy: Literal["UNTRACKED", "BATCH", "SERIAL"]
    batch_key: UUID | None
    batch_code: str | None
    shade: str | None
    calibre: str | None
    base_unit: str
    quantity: str
    collected: str
    remaining: str
    stock_version: int
    serials: list[SalesCollectionSerialOption] = Field(default_factory=list)


class SalesCollectionOptionsRead(BaseModel):
    invoice_key: UUID
    invoice_number: str
    payment_status: Literal["PAID"] = "PAID"
    fulfilment_status: Literal[
        "AWAITING_COLLECTION", "PARTIALLY_COLLECTED", "COLLECTED"
    ]
    branch_id: int
    branch_settings_version: int
    assignment_version: int
    counters: list[SalesCollectionCounterOption]
    lines: list[SalesCollectionLineOption]
    reservations: list[SalesCollectionReservationOption]


class SalesCollectionAllocationRead(BaseModel):
    line_key: UUID
    reservation_key: UUID
    balance_id: int
    location_id: int
    batch_key: UUID | None
    handover_operation_key: UUID
    quantity: str
    base_unit: str
    serials: list[SalesCollectionSerialOption] = Field(default_factory=list)


class SalesCollectionRead(BaseModel):
    collection_key: UUID
    operation_key: UUID
    invoice_key: UUID
    branch_id: int
    counter_id: int
    branch_settings_version: int
    counter_settings_version: int
    assignment_version: int
    business_date: date
    collector_name: str
    collector_contact: str
    collected_at: datetime
    collected_by: int
    payment_status: Literal["PAID"] = "PAID"
    fulfilment_status: Literal["PARTIALLY_COLLECTED", "COLLECTED"]
    allocations: list[SalesCollectionAllocationRead]


class SalesCollectionCreateResult(BaseModel):
    collection: SalesCollectionRead
    replayed: bool

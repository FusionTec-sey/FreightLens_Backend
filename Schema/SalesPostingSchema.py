"""Typed T13 requests and immutable sales-posting reads."""
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


MONEY_PATTERN = r"^[0-9]{1,18}(?:\.[0-9]{1,2})?$"
QUANTITY_PATTERN = r"^[0-9]{1,12}(?:\.[0-9]{1,6})?$"
DIGEST_PATTERN = r"^[0-9a-f]{64}$"


def _nonzero(value: UUID) -> UUID:
    if value.int == 0:
        raise ValueError("UUID must be nonzero")
    return value


class SalesPostingTenderInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tender_key: UUID
    method_key: UUID
    expected_method_version: int = Field(gt=0, strict=True)
    mapping_key: UUID
    expected_mapping_version: int = Field(gt=0, strict=True)
    amount_scr: str = Field(pattern=MONEY_PATTERN, max_length=21)

    @field_validator("tender_key", "method_key", "mapping_key")
    @classmethod
    def valid_key(cls, value: UUID) -> UUID:
        return _nonzero(value)

    @field_validator("amount_scr")
    @classmethod
    def positive_amount(cls, value: str) -> str:
        if Decimal(value) <= 0:
            raise ValueError("Tender amount must be positive")
        return value


class SalesPostingAttemptCreate(BaseModel):
    """Create an immutable attempt; totals/configuration are resolved server-side."""

    model_config = ConfigDict(extra="forbid")
    attempt_key: UUID
    operation_key: UUID
    document_key: UUID
    expected_draft_version: int = Field(gt=0, strict=True)
    pricing_snapshot_key: UUID
    expected_pricing_fingerprint: str = Field(pattern=DIGEST_PATTERN)
    counter_key: UUID
    expected_branch_settings_version: int = Field(gt=0, strict=True)
    expected_counter_settings_version: int = Field(gt=0, strict=True)
    expected_assignment_version: int = Field(gt=0, strict=True)
    tenders: list[SalesPostingTenderInput] = Field(min_length=1, max_length=20)

    @field_validator("attempt_key", "operation_key", "document_key", "pricing_snapshot_key", "counter_key")
    @classmethod
    def valid_key(cls, value: UUID) -> UUID:
        return _nonzero(value)

    @model_validator(mode="after")
    def unique_tenders(self):
        if len({item.tender_key for item in self.tenders}) != len(self.tenders):
            raise ValueError("Tender identities must be unique")
        return self


class SalesCardConfirmationAppend(BaseModel):
    """Append one provider observation. Only a hash of its reference is accepted."""

    model_config = ConfigDict(extra="forbid")
    confirmation_key: UUID
    attempt_key: UUID
    tender_key: UUID
    expected_sequence: int = Field(gt=0, strict=True)
    outcome: Literal["UNKNOWN", "CONFIRMED", "DECLINED"]
    provider_reference_hash: str | None = Field(default=None, pattern=DIGEST_PATTERN)

    @field_validator("confirmation_key", "attempt_key", "tender_key")
    @classmethod
    def valid_key(cls, value: UUID) -> UUID:
        return _nonzero(value)

    @model_validator(mode="after")
    def evidence_matches_outcome(self):
        if self.outcome == "CONFIRMED" and self.provider_reference_hash is None:
            raise ValueError("Confirmed card outcome requires a hashed provider reference")
        if self.outcome != "CONFIRMED" and self.provider_reference_hash is not None:
            raise ValueError("Only confirmed outcomes may carry provider-reference evidence")
        return self


class SalesReservationBindingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_line_key: UUID
    reservation_key: UUID
    quantity: str = Field(pattern=QUANTITY_PATTERN, max_length=19)

    @field_validator("source_line_key", "reservation_key")
    @classmethod
    def valid_key(cls, value: UUID) -> UUID:
        return _nonzero(value)

    @field_validator("quantity")
    @classmethod
    def positive_quantity(cls, value: str) -> str:
        if Decimal(value) <= 0:
            raise ValueError("Reservation quantity must be positive")
        return value


class SalesPostingFinalize(BaseModel):
    """Finalize only the named immutable attempt and exact commitments."""

    model_config = ConfigDict(extra="forbid")
    attempt_key: UUID
    operation_key: UUID
    invoice_key: UUID
    reservations: list[SalesReservationBindingInput] = Field(min_length=1, max_length=500)
    expected_card_confirmations: list[UUID] = Field(default_factory=list, max_length=20)

    @field_validator("attempt_key", "operation_key", "invoice_key")
    @classmethod
    def valid_key(cls, value: UUID) -> UUID:
        return _nonzero(value)

    @field_validator("expected_card_confirmations")
    @classmethod
    def valid_confirmations(cls, value: list[UUID]) -> list[UUID]:
        if any(item.int == 0 for item in value):
            raise ValueError("Confirmation UUIDs must be nonzero")
        if len(set(value)) != len(value):
            raise ValueError("Confirmation identities must be unique")
        return value

    @model_validator(mode="after")
    def unique_reservations(self):
        keys = [item.reservation_key for item in self.reservations]
        if len(set(keys)) != len(keys):
            raise ValueError("A reservation can be committed only once")
        return self


class SalesPostingTenderRead(BaseModel):
    tender_key: UUID
    method_key: UUID
    method_version: int
    mapping_key: UUID
    mapping_version: int
    kind: Literal["CASH", "CARD"]
    amount_scr: str


class SalesCardConfirmationRead(BaseModel):
    confirmation_key: UUID
    tender_key: UUID
    sequence: int
    outcome: Literal["UNKNOWN", "CONFIRMED", "DECLINED"]
    provider_reference_hash: str | None
    observed_at: datetime


class SalesPostingAttemptRead(BaseModel):
    attempt_key: UUID
    operation_key: UUID
    document_key: UUID
    draft_version: int
    pricing_snapshot_key: UUID
    pricing_fingerprint: str
    branch_id: int
    counter_id: int
    counter_key: UUID
    branch_settings_version: int
    counter_settings_version: int
    assignment_version: int
    business_date: date
    customer_key: UUID
    customer_version: int
    currency: Literal["SCR"]
    gross_total_scr: str
    net_total_scr: str
    tax_total_scr: str
    status: Literal["AWAITING_CARD", "READY", "DECLINED", "POSTED"]
    created_at: datetime
    tenders: list[SalesPostingTenderRead]
    card_confirmations: list[SalesCardConfirmationRead]
    invoice_key: UUID | None = None


class SalesPostingCreateResult(BaseModel):
    attempt_key: UUID
    status: Literal["AWAITING_CARD", "READY", "DECLINED", "POSTED"]
    replayed: bool


class SalesPostingCounterOption(BaseModel):
    counter_key: UUID
    code: str
    name: str
    version: int


class SalesPostingPaymentOption(BaseModel):
    method_key: UUID
    method_version: int
    code: str
    label: str
    kind: Literal["CASH", "CARD"]
    mapping_key: UUID
    mapping_version: int


class SalesPostingReservationOption(BaseModel):
    source_line_key: UUID
    reservation_key: UUID
    quantity: str


class SalesPostingOptionsRead(BaseModel):
    document_key: UUID
    draft_version: int
    branch_id: int
    branch_settings_version: int
    assignment_version: int
    counters: list[SalesPostingCounterOption]
    payment_methods: list[SalesPostingPaymentOption]
    reservations: list[SalesPostingReservationOption]


class SalesInvoiceLineRead(BaseModel):
    line_key: UUID
    source_line_key: UUID
    position: int
    product_id: int
    product_name: str
    sku: str
    policy_version: int
    quantity: str
    unit: str
    base_quantity: str
    base_unit: str
    gross_unit_scr: str
    gross_total_scr: str
    net_total_scr: str
    tax_total_scr: str
    tax_treatment: Literal["STANDARD", "ZERO_RATED", "EXEMPT"]
    tax_rate: str
    pricing_snapshot: dict


class SalesInvoicePaymentRead(BaseModel):
    payment_key: UUID
    tender_key: UUID
    kind: Literal["CASH", "CARD"]
    amount_scr: str
    confirmation_key: UUID | None


class SalesInvoiceReservationRead(BaseModel):
    line_key: UUID
    reservation_key: UUID
    quantity: str


class SalesInvoiceRead(BaseModel):
    invoice_key: UUID
    attempt_key: UUID
    operation_key: UUID
    invoice_number: str
    document_key: UUID
    draft_version: int
    branch_id: int
    counter_id: int
    branch_settings_version: int
    counter_settings_version: int
    assignment_version: int
    customer_key: UUID
    customer_version: int
    customer_snapshot: dict
    branch_snapshot: dict
    business_date: date
    issued_at: datetime
    currency: Literal["SCR"]
    gross_total_scr: str
    net_total_scr: str
    tax_total_scr: str
    payment_status: Literal["PAID"] = "PAID"
    fulfilment_status: Literal["AWAITING_COLLECTION"] = "AWAITING_COLLECTION"
    lines: list[SalesInvoiceLineRead]
    payments: list[SalesInvoicePaymentRead]
    reservations: list[SalesInvoiceReservationRead]


class SalesPostingFinalizeResult(BaseModel):
    invoice: SalesInvoiceRead
    replayed: bool

"""Strict request and response contracts for invoice-bound customer returns."""
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ReturnCondition = Literal["UNOPENED", "OPENED", "DAMAGED", "UNKNOWN"]
ReturnStatus = Literal["REQUESTED", "APPROVED", "REJECTED", "CREDITED"]


def _nonzero(value: UUID) -> UUID:
    if value.int == 0:
        raise ValueError("UUID must be nonzero")
    return value


def _exact_decimal(value) -> Decimal:
    if isinstance(value, float):
        raise ValueError("Return quantity must be an exact decimal string")
    result = value if isinstance(value, Decimal) else Decimal(value)
    if not result.is_finite() or result <= 0:
        raise ValueError("Return quantity must be positive")
    return result


class SalesReturnClaimLineInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    invoice_line_key: UUID
    handover_allocation_key: UUID
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    condition: ReturnCondition

    @field_validator("invoice_line_key", "handover_allocation_key")
    @classmethod
    def valid_key(cls, value: UUID) -> UUID:
        return _nonzero(value)

    @field_validator("quantity", mode="before")
    @classmethod
    def exact_quantity(cls, value):
        return _exact_decimal(value)


class SalesReturnClaimCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    return_key: UUID
    operation_key: UUID
    invoice_key: UUID
    expected_invoice_version: Literal[1]
    returner_name: str = Field(min_length=1, max_length=150)
    returner_contact: str = Field(min_length=1, max_length=50)
    reason: str = Field(min_length=1, max_length=1000)
    lines: list[SalesReturnClaimLineInput] = Field(min_length=1, max_length=500)

    @field_validator("return_key", "operation_key", "invoice_key")
    @classmethod
    def valid_key(cls, value: UUID) -> UUID:
        return _nonzero(value)

    @model_validator(mode="after")
    def unique_handover_allocations(self):
        keys = [line.handover_allocation_key for line in self.lines]
        if len(keys) != len(set(keys)):
            raise ValueError("A handover allocation may appear only once per return claim")
        return self


class SalesReturnReview(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    operation_key: UUID
    expected_version: Literal[1]
    outcome: Literal["APPROVED", "REJECTED"]
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("operation_key")
    @classmethod
    def valid_key(cls, value: UUID) -> UUID:
        return _nonzero(value)


class SalesReturnClaimLineRead(BaseModel):
    invoice_line_key: UUID
    handover_allocation_key: UUID
    product_id: int
    product_name: str
    sku: str
    balance_id: int
    location_id: int
    batch_key: UUID | None
    quantity: str
    base_unit: str
    condition: ReturnCondition


class SalesReturnReviewRead(BaseModel):
    case_key: UUID
    outcome: Literal["APPROVED", "REJECTED"] | None
    reviewer_id: int | None
    reason: str | None
    reviewed_at: datetime | None


class SalesReturnClaimRead(BaseModel):
    return_key: UUID
    operation_key: UUID
    invoice_key: UUID
    invoice_number: str
    branch_id: int
    customer_key: UUID
    returner_name: str
    returner_contact: str
    reason: str
    status: ReturnStatus
    version: Literal[1, 2, 3]
    requested_by: int
    requested_at: datetime
    review: SalesReturnReviewRead
    estimated_gross_credit_scr: str
    lines: list[SalesReturnClaimLineRead]


class SalesReturnClaimCreateResult(BaseModel):
    claim: SalesReturnClaimRead
    replayed: bool


class SalesReturnReviewResult(BaseModel):
    claim: SalesReturnClaimRead
    replayed: bool


class SalesReturnLineOption(BaseModel):
    invoice_line_key: UUID
    product_id: int
    product_name: str
    sku: str
    base_unit: str
    handed_over: str
    accepted_returned: str
    pending_return: str
    returnable: str


class SalesReturnHandoverOption(BaseModel):
    handover_allocation_key: UUID
    collection_key: UUID
    invoice_line_key: UUID
    balance_id: int
    location_id: int
    location_code: str
    location_name: str
    batch_key: UUID | None
    batch_code: str | None
    shade: str | None
    calibre: str | None
    base_unit: str
    handed_over: str
    accepted_returned: str
    pending_return: str
    returnable: str
    collected_at: datetime


class SalesReturnOptionsRead(BaseModel):
    invoice_key: UUID
    invoice_number: str
    invoice_version: Literal[1] = 1
    customer_key: UUID
    customer_name: str
    branch_id: int
    branch_name: str
    lines: list[SalesReturnLineOption]
    handovers: list[SalesReturnHandoverOption]


class SalesReturnProcessingBalance(BaseModel):
    balance_id: int
    expected_stock_version: int
    expected_valuation_version: int


class SalesReturnProcessingOptionsRead(BaseModel):
    return_key: UUID
    claim_version: Literal[2]
    option_version: Literal[1] = 1
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    branch_id: int
    gross_credit_scr: str
    net_credit_scr: str
    tax_credit_scr: str
    invoice_debt_applied_scr: str
    customer_credit_scr: str
    balances: list[SalesReturnProcessingBalance]


class SalesReturnCreditNoteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_key: UUID
    expected_claim_version: Literal[2]
    expected_option_version: Literal[1]
    expected_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("operation_key")
    @classmethod
    def valid_key(cls, value: UUID) -> UUID:
        return _nonzero(value)


class SalesCreditNoteLineRead(BaseModel):
    invoice_line_key: UUID
    handover_allocation_key: UUID
    quantity: str
    base_unit: str
    gross_credit_scr: str
    net_credit_scr: str
    tax_credit_scr: str


class SalesCreditNoteRead(BaseModel):
    credit_note_key: UUID
    credit_note_number: str
    return_key: UUID
    invoice_key: UUID
    invoice_number: str
    branch_id: int
    customer_key: UUID
    currency: Literal["SCR"] = "SCR"
    gross_credit_scr: str
    net_credit_scr: str
    tax_credit_scr: str
    invoice_debt_applied_scr: str
    customer_credit_scr: str
    issued_at: datetime
    issued_by: int
    lines: list[SalesCreditNoteLineRead]


class SalesReturnCreditNoteResult(BaseModel):
    credit_note: SalesCreditNoteRead
    replayed: bool


class SalesReturnClaimPage(BaseModel):
    items: list[SalesReturnClaimRead]
    total: int
    page: int
    pages: int
    limit: int


class SalesCreditNotePage(BaseModel):
    items: list[SalesCreditNoteRead]
    total: int
    page: int
    pages: int
    limit: int

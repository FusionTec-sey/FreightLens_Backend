"""Declared receipt price/FX evidence; never a client-authoritative valuation."""
from datetime import datetime
from decimal import Context, Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from Services.inventory_costing_service import MAX_VALUE, QUANTUM, _number


class ReceiptCostDeclaration(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, str_strip_whitespace=True)
    document_id: UUID
    fx_document_id: UUID | None = None
    source_currency: str = Field(pattern=r'^[A-Z]{3}$')
    unit_price_source: str
    exchange_rate_to_scr: str
    justification: str = Field(min_length=1, max_length=1000)

    @field_validator('document_id', 'fx_document_id')
    @classmethod
    def nonzero_document(cls, value):
        if value is not None and not value.int:
            raise ValueError('Nonzero evidence document required')
        return value

    @field_validator('unit_price_source')
    @classmethod
    def exact_price(cls, value):
        try:
            return format(_number(Decimal(value), 'Receipt unit price',
                MAX_VALUE, positive=True), '.6f')
        except InvalidOperation as error:
            raise ValueError('Exact receipt unit price required') from error

    @field_validator('exchange_rate_to_scr')
    @classmethod
    def exact_rate(cls, value):
        try:
            rate = Decimal(value)
            if not rate.is_finite() or rate <= 0 or rate > Decimal('9999999999.99999999'):
                raise ValueError('Positive bounded SCR-per-source-unit rate required')
            with localcontext(Context(prec=60, rounding=ROUND_HALF_UP)):
                normalized = rate.quantize(Decimal('.00000001'))
            if rate != normalized:
                raise ValueError('Exchange rate allows at most eight decimal places')
            return format(normalized, '.8f')
        except InvalidOperation as error:
            raise ValueError('Exact decimal exchange rate required') from error

    @model_validator(mode='after')
    def currency_evidence(self):
        if self.source_currency == 'SCR' and Decimal(self.exchange_rate_to_scr) != 1:
            raise ValueError('SCR receipt must use exchange rate 1')
        if self.source_currency != 'SCR' and self.fx_document_id is None:
            raise ValueError('Foreign-currency receipt requires explicit FX evidence')
        return self

    def values(self, receipt_quantity: Decimal):
        quantity = _number(receipt_quantity, 'Receipt source quantity',
            Decimal('999999999999.999999'), positive=True)
        with localcontext(Context(prec=60, rounding=ROUND_HALF_UP)):
            source = (quantity * Decimal(self.unit_price_source)).quantize(QUANTUM)
            scr = (source * Decimal(self.exchange_rate_to_scr)).quantize(QUANTUM)
        return (format(_number(source, 'Receipt goods source value', MAX_VALUE,
                    positive=True), '.6f'),
                format(_number(scr, 'Receipt goods SCR value', MAX_VALUE,
                    positive=True), '.6f'))


class ReceiptCostReviewRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    operation_key: UUID
    reason: str = Field(min_length=1, max_length=1000)
    declaration: ReceiptCostDeclaration

    @field_validator('operation_key')
    @classmethod
    def nonzero_operation(cls, value):
        if not value.int:
            raise ValueError('Nonzero operation identity required')
        return value


class ReceiptCostDocumentRead(BaseModel):
    id: UUID
    label: str
    doc_type: str


class ReceiptCostCaseRead(BaseModel):
    case_key: UUID
    manifest_key: UUID
    version: int
    status: Literal['REQUESTED', 'APPROVED', 'REJECTED', 'CONSUMED']
    reason: str
    requestor_id: int
    reviewer_id: int | None = None
    review_reason: str | None = None
    requested_at: datetime
    declaration: ReceiptCostDeclaration
    receipt_quantity: str
    goods_value_source: str
    goods_value_scr: str
    documents: list[ReceiptCostDocumentRead]
    physical_posting_enabled: Literal[False] = False

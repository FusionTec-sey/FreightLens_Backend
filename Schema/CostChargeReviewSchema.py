"""Explicit charge declaration for evidence-bound review, never automatic tax/FX."""
from datetime import date
from decimal import Context, Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from Schema.CostChargeSchema import invoice_identity
from Services.inventory_costing_service import _number, MAX_VALUE, QUANTUM


class CostChargeDeclaration(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, str_strip_whitespace=True)
    supplier_id: int = Field(gt=0, strict=True)
    invoice_reference: str
    invoice_date: date
    document_id: UUID
    source_currency: str = Field(pattern=r'^[A-Z]{3}$')
    eligible_amount: str
    exchange_rate_to_scr: str
    fx_document_id: UUID | None = None
    capitalisation_reason: str = Field(min_length=1, max_length=1000)

    @field_validator('invoice_reference')
    @classmethod
    def reference(cls, value):
        invoice_identity(value)
        return value

    @field_validator('document_id', 'fx_document_id')
    @classmethod
    def nonzero(cls, value):
        if value is not None and not value.int: raise ValueError('Nonzero evidence document required')
        return value

    @field_validator('eligible_amount')
    @classmethod
    def amount(cls, value):
        try: return format(_number(Decimal(value), 'Eligible amount', MAX_VALUE, positive=True), '.6f')
        except InvalidOperation as error: raise ValueError('Exact decimal amount required') from error

    @field_validator('exchange_rate_to_scr')
    @classmethod
    def rate(cls, value):
        try:
            rate = Decimal(value)
            if not rate.is_finite() or rate <= 0 or rate > Decimal('9999999999.99999999'):
                raise ValueError('Positive bounded SCR-per-source-unit rate required')
            with localcontext(Context(prec=60, rounding=ROUND_HALF_UP)):
                normalized = rate.quantize(Decimal('.00000001'))
            if rate != normalized: raise ValueError('Exchange rate allows at most eight decimal places')
            return format(normalized, '.8f')
        except InvalidOperation as error: raise ValueError('Exact decimal exchange rate required') from error

    @model_validator(mode='after')
    def currency_evidence(self):
        if self.source_currency == 'SCR' and Decimal(self.exchange_rate_to_scr) != 1:
            raise ValueError('SCR charge must use exchange rate 1')
        if self.source_currency != 'SCR' and self.fx_document_id is None:
            raise ValueError('Foreign currency requires explicit FX evidence')
        self.amount_scr()  # Reject overflow or a positive charge rounded to zero.
        return self

    def amount_scr(self):
        with localcontext(Context(prec=60, rounding=ROUND_HALF_UP)):
            value = (Decimal(self.eligible_amount) * Decimal(self.exchange_rate_to_scr)).quantize(QUANTUM)
        return format(_number(value, 'Converted charge', MAX_VALUE, positive=True), '.6f')

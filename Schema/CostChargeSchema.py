"""Trusted adapter contract, NOT a public request or proof of verified evidence."""
import re
from uuid import UUID
from decimal import Decimal, InvalidOperation
from pydantic import BaseModel, ConfigDict, Field, field_validator
from Services.inventory_costing_service import _number, MAX_VALUE


def invoice_identity(reference):
    # Conservative collision policy: formatting cannot create another charge.
    # Leading zeros remain significant; ambiguous collisions need human review.
    if not isinstance(reference, str) or not 1 <= len(reference.strip()) <= 160:
        raise ValueError('Explicit supplier invoice reference required')
    reference = reference.strip().upper()
    if not re.fullmatch(r'[A-Z0-9 ./_-]+', reference):
        raise ValueError('Invoice reference contains unsupported characters')
    identity = re.sub(r'[ ./_-]', '', reference)
    if not identity: raise ValueError('Invoice reference requires letters or digits')
    return identity


class CostChargeEvidence(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, str_strip_whitespace=True)
    supplier_id: int = Field(gt=0, strict=True)
    invoice_reference: str
    document_id: UUID
    source_fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    amount_scr: str

    @field_validator('invoice_reference')
    @classmethod
    def valid_reference(cls, value):
        invoice_identity(value)
        return value

    @field_validator('amount_scr')
    @classmethod
    def exact_amount(cls, value):
        try:
            return format(_number(Decimal(value), 'Verified charge', MAX_VALUE, positive=True), '.6f')
        except InvalidOperation as error:
            raise ValueError('Verified charge must be an exact decimal string') from error

    @field_validator('document_id')
    @classmethod
    def real_key(cls, value):
        if not value.int: raise ValueError('Nonzero evidence document required')
        return value

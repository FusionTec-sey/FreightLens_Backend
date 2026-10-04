"""Typed sales-pricing configuration; money enters as exact decimal text."""
import re
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


MONEY_PATTERN = re.compile(r"(?:0|[1-9][0-9]{0,17})(?:\.[0-9]{1,6})?")
RATE_PATTERN = re.compile(r"(?:0|[1-9](?:\.[0-9]{1,8})?|0\.[0-9]{1,8})")


def _nonzero_uuid(value, label):
    if not value.int:
        raise ValueError(f"{label} must be nonzero")
    return value


class TaxRuleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)
    treatment: Literal["STANDARD", "ZERO_RATED", "EXEMPT"]
    rate: str
    is_enabled: bool = Field(strict=True)

    @field_validator("rate")
    @classmethod
    def exact_rate(cls, value):
        if not isinstance(value, str) or not RATE_PATTERN.fullmatch(value):
            raise ValueError("Tax rate must be exact decimal text with up to eight places")
        rate = Decimal(value)
        if rate >= Decimal("10"):
            raise ValueError("Tax rate is outside the supported range")
        return value

    @model_validator(mode="after")
    def treatment_rate(self):
        rate = Decimal(self.rate)
        if self.treatment == "STANDARD" and rate <= 0:
            raise ValueError("Standard-rated supply requires a positive rate")
        if self.treatment != "STANDARD" and rate != 0:
            raise ValueError("Zero-rated and exempt supplies require a zero rate")
        return self


class TaxRuleSave(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    operation_key: UUID
    expected_version: int = Field(ge=0, strict=True)
    code: str = Field(pattern=r"^[A-Z0-9][A-Z0-9_-]{0,31}$")
    config: TaxRuleConfig
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("operation_key")
    @classmethod
    def valid_operation(cls, value):
        return _nonzero_uuid(value, "Operation key")


class TaxRuleRead(BaseModel):
    tax_rule_key: UUID
    code: str
    version: int
    name: str
    treatment: Literal["STANDARD", "ZERO_RATED", "EXEMPT"]
    rate: str
    is_enabled: bool


class BranchProductPriceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    gross_unit_scr: str
    floor_gross_unit_scr: str | None = None
    is_enabled: bool = Field(strict=True)

    @field_validator("gross_unit_scr", "floor_gross_unit_scr")
    @classmethod
    def exact_money(cls, value, info):
        if value is None:
            return value
        if not isinstance(value, str) or not MONEY_PATTERN.fullmatch(value):
            raise ValueError("SCR price must be exact decimal text with up to six places")
        amount = Decimal(value)
        if amount >= Decimal("1000000000000000000"):
            raise ValueError("SCR price is outside the supported range")
        if info.field_name == "gross_unit_scr" and amount <= 0:
            raise ValueError("Gross unit price must be positive")
        return value

    @model_validator(mode="after")
    def floor_not_above_store_price(self):
        if (self.floor_gross_unit_scr is not None
                and Decimal(self.floor_gross_unit_scr) > Decimal(self.gross_unit_scr)):
            raise ValueError("Store price cannot be below its approval floor")
        return self


class BranchProductPriceSave(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    operation_key: UUID
    expected_version: int = Field(ge=0, strict=True)
    branch_id: int = Field(gt=0, strict=True)
    product_id: int = Field(gt=0, strict=True)
    unit: str = Field(min_length=1, max_length=50)
    config: BranchProductPriceConfig
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("operation_key")
    @classmethod
    def valid_operation(cls, value):
        return _nonzero_uuid(value, "Operation key")


class BranchProductPriceRead(BaseModel):
    price_key: UUID
    branch_id: int
    product_id: int
    unit: str
    version: int
    gross_unit_scr: str
    floor_gross_unit_scr: str | None
    is_enabled: bool


class ProductTaxAssignmentSave(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    operation_key: UUID
    expected_version: int = Field(ge=0, strict=True)
    product_id: int = Field(gt=0, strict=True)
    tax_rule_key: UUID
    is_enabled: bool = Field(strict=True)
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("operation_key", "tax_rule_key")
    @classmethod
    def valid_keys(cls, value, info):
        return _nonzero_uuid(value, info.field_name.replace("_", " ").title())


class ProductTaxAssignmentRead(BaseModel):
    assignment_key: UUID
    product_id: int
    version: int
    tax_rule_key: UUID
    is_enabled: bool


class CustomerPriceAgreementConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    gross_unit_scr: str
    valid_from: datetime
    valid_until: datetime | None = None
    terms_reference: str = Field(min_length=1, max_length=200)
    is_enabled: bool = Field(strict=True)

    @field_validator("gross_unit_scr")
    @classmethod
    def exact_price(cls, value):
        if not isinstance(value, str) or not MONEY_PATTERN.fullmatch(value):
            raise ValueError("SCR price must be exact decimal text with up to six places")
        amount = Decimal(value)
        if amount <= 0 or amount >= Decimal("1000000000000000000"):
            raise ValueError("Customer price is outside the supported range")
        return value

    @field_validator("valid_from", "valid_until")
    @classmethod
    def timezone_required(cls, value):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Agreement times must include a timezone")
        return value

    @model_validator(mode="after")
    def valid_period(self):
        if self.valid_until is not None and self.valid_until <= self.valid_from:
            raise ValueError("Agreement end must be after its start")
        return self


class CustomerPriceAgreementSave(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    operation_key: UUID
    expected_version: int = Field(ge=0, strict=True)
    customer_key: UUID
    branch_id: int = Field(gt=0, strict=True)
    product_id: int = Field(gt=0, strict=True)
    unit: str = Field(min_length=1, max_length=50)
    config: CustomerPriceAgreementConfig
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("operation_key", "customer_key")
    @classmethod
    def valid_keys(cls, value, info):
        return _nonzero_uuid(value, info.field_name.replace("_", " ").title())


class CustomerPriceAgreementRead(BaseModel):
    agreement_key: UUID
    customer_key: UUID
    branch_id: int
    product_id: int
    unit: str
    version: int
    gross_unit_scr: str
    valid_from: datetime
    valid_until: datetime | None
    terms_reference: str
    is_enabled: bool


class SalesPricingPreviewLine(BaseModel):
    line_key: UUID
    product_id: int
    quantity: str
    selected_source: Literal["STORE", "CUSTOMER_AGREEMENT"]
    selected_reference_key: str
    selected_version: int
    gross_unit_scr: str
    store_price_key: str
    store_price_version: int
    store_gross_unit_scr: str
    floor_gross_unit_scr: str | None
    requires_floor_approval: bool
    tax_code: str
    tax_version: int
    tax_treatment: Literal["STANDARD", "ZERO_RATED", "EXEMPT"]
    tax_rate: str
    gross_scr: str
    net_scr: str
    tax_scr: str


class SalesPricingPreviewRead(BaseModel):
    document_key: UUID
    draft_version: int
    status: Literal["READY"] = "READY"
    currency: Literal["SCR"] = "SCR"
    policy: Literal["best-eligible-tax-inclusive-invoice-round-v1"]
    priced_at: datetime
    lines: list[SalesPricingPreviewLine]
    gross_total_scr: str
    net_total_scr: str
    tax_total_scr: str
    requires_floor_approval: bool
    posting_enabled: Literal[False] = False


class SalesTransactionPricingPrepare(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_key: UUID
    expected_draft_version: int = Field(gt=0, strict=True)
    floor_case_key: UUID | None = None

    @field_validator("operation_key", "floor_case_key")
    @classmethod
    def nonzero_keys(cls, value, info):
        if value is not None:
            return _nonzero_uuid(value,
                info.field_name.replace("_", " ").title())
        return value


class SalesTransactionPricingRead(BaseModel):
    pricing_snapshot_key: UUID
    document_key: UUID
    draft_version: int
    status: Literal["PREPARED"] = "PREPARED"
    priced_at: datetime
    currency: Literal["SCR"] = "SCR"
    policy: str
    pricing: dict
    pricing_fingerprint: str
    gross_total_scr: str
    net_total_scr: str
    tax_total_scr: str
    requires_floor_approval: bool
    floor_case_key: UUID | None
    created_at: datetime
    created_by: int
    posting_enabled: Literal[False] = False
    replayed: bool = False

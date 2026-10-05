"""Typed T20A account-role configuration; no journal posting contract."""
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


AccountRole = Literal[
    "SALES_REVENUE",
    "OUTPUT_TAX_PAYABLE",
    "CUSTOMER_CREDIT_LIABILITY",
    "COST_OF_GOODS_SOLD",
    "INVENTORY_ASSET",
    "CASH_OVER_SHORT",
    "CASH_DEPOSIT_CLEARING",
]


def _nonzero(value: UUID) -> UUID:
    if not value.int:
        raise ValueError("UUID must be nonzero")
    return value


class AccountMappingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    account_ref: str = Field(
        min_length=1, max_length=64, pattern=r"^[A-Z0-9][A-Z0-9_.:-]{0,63}$"
    )
    label: str = Field(min_length=1, max_length=120)
    is_enabled: bool = Field(strict=True)


class AccountMappingSave(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    operation_key: UUID
    expected_version: int = Field(ge=0, strict=True)
    branch_id: int = Field(gt=0, strict=True)
    account_role: AccountRole
    config: AccountMappingConfig
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("operation_key")
    @classmethod
    def valid_key(cls, value: UUID) -> UUID:
        return _nonzero(value)


class AccountMappingRead(BaseModel):
    mapping_key: UUID
    branch_id: int
    account_role: AccountRole
    version: int
    account_ref: str
    label: str
    is_enabled: bool


class AccountMappingRevisionRead(AccountMappingRead):
    operation_key: UUID
    reason: str


class AccountMappingSaveResult(BaseModel):
    key: UUID
    version: int
    replayed: bool


class AccountMappingLookupRead(BaseModel):
    status: Literal["READY", "BLOCKED"]
    reason: Literal["BRANCH_DISABLED", "MAPPING_MISSING", "MAPPING_DISABLED"] | None = None
    branch_id: int
    account_role: AccountRole
    mapping_key: UUID | None = None
    mapping_version: int | None = None
    account_ref: str | None = None
    label: str | None = None

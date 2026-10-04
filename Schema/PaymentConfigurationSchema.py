"""Typed synthetic payment configuration. Account refs are opaque ledger labels."""
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator


def nonzero(value):
    if not value.int:
        raise ValueError("UUID must be nonzero")
    return value


class MethodConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    label: str = Field(min_length=1, max_length=120)
    kind: Literal["CASH", "CARD"]
    is_enabled: bool = Field(strict=True)


class MethodSave(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    operation_key: UUID
    expected_version: int = Field(ge=0, strict=True)
    code: str = Field(pattern=r"^[A-Z0-9][A-Z0-9_-]{0,31}$")
    config: MethodConfig
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("operation_key")
    @classmethod
    def valid_key(cls, value):
        return nonzero(value)


class MethodRead(BaseModel):
    method_key: UUID
    code: str
    version: int
    label: str
    kind: Literal["CASH", "CARD"]
    is_enabled: bool


class MappingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    account_ref: str = Field(min_length=1, max_length=64,
                             pattern=r"^[A-Z0-9][A-Z0-9_.:-]{0,63}$")
    label: str = Field(min_length=1, max_length=120)
    is_enabled: bool = Field(strict=True)


class MappingSave(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    operation_key: UUID
    expected_version: int = Field(ge=0, strict=True)
    branch_id: int = Field(gt=0, strict=True)
    method_key: UUID
    config: MappingConfig
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("operation_key", "method_key")
    @classmethod
    def valid_key(cls, value):
        return nonzero(value)


class MappingRead(BaseModel):
    mapping_key: UUID
    branch_id: int
    method_key: UUID
    version: int
    account_ref: str
    label: str
    is_enabled: bool


class SaveResult(BaseModel):
    key: UUID
    version: int
    replayed: bool


class LookupRead(BaseModel):
    status: Literal["READY", "BLOCKED"]
    reason: str | None = None
    branch_id: int
    method_key: UUID
    mapping_key: UUID | None = None
    mapping_version: int | None = None
    account_ref: str | None = None
    label: str | None = None


class BranchOption(BaseModel):
    id: int
    code: str
    name: str
    is_active: bool

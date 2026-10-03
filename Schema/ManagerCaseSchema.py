from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator
from Schema.InventoryPolicySchema import InventoryPolicyConfig


class PolicyCaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    operation_key: UUID
    product_id: int = Field(gt=0, strict=True)
    expected_source_version: int = Field(gt=0, strict=True)
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("operation_key")
    @classmethod
    def nonzero(cls, value):
        if not value.int: raise ValueError("Operation key must be nonzero")
        return value


class PolicyCaseReview(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    operation_key: UUID
    expected_version: Literal[1]
    outcome: Literal["APPROVED", "REJECTED"]
    reason: str = Field(min_length=1, max_length=1000)


class CaseActionRead(BaseModel):
    case_key: UUID
    version: int
    status: Literal["REQUESTED", "APPROVED", "REJECTED"]
    replayed: bool


class PolicyCaseRead(BaseModel):
    case_key: UUID
    version: int
    status: Literal["REQUESTED", "APPROVED", "REJECTED", "CONSUMED"]
    product_id: int
    product_name: str
    source_version: int
    expected_active_version: int = 0
    transition: Literal["STANDARD", "EXTEND_UNITS"] = "STANDARD"
    config: InventoryPolicyConfig
    reason: str
    requestor_id: int
    reviewer_id: int | None
    review_reason: str | None
    requested_at: datetime

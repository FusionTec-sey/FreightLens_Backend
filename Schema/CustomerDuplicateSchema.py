"""Duplicate review is an assessment, never authority to merge balances."""
from typing import Literal
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator


class CustomerDuplicateRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    operation_key: UUID
    customer_key: UUID
    other_customer_key: UUID
    expected_customer_version: int = Field(ge=1, strict=True)
    expected_other_version: int = Field(ge=1, strict=True)
    assessment: Literal['SAME_CUSTOMER', 'DISTINCT_CUSTOMERS']
    reason: str = Field(min_length=1, max_length=1000)

    @model_validator(mode='after')
    def distinct_identities(self):
        if self.customer_key == self.other_customer_key:
            raise ValueError('Choose two different customer identities')
        if not self.customer_key.int or not self.other_customer_key.int or not self.operation_key.int:
            raise ValueError('Nonzero request and customer identities required')
        return self


class DuplicateProfileReference(BaseModel):
    customer_key: UUID
    version: int


class CustomerDuplicateRead(BaseModel):
    case_key: UUID
    version: int
    status: Literal['REQUESTED', 'APPROVED', 'REJECTED']
    source_version: int
    customers: list[DuplicateProfileReference]
    assessment: Literal['SAME_CUSTOMER', 'DISTINCT_CUSTOMERS']
    merge_authorized: Literal[False] = False
    reason: str
    requestor_id: int
    reviewer_id: int | None
    review_reason: str | None
    requested_at: datetime

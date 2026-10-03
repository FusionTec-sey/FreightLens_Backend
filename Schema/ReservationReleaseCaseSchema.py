from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class ReleaseCaseRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    operation_key: UUID
    reservation_key: UUID
    expected_source_version: int = Field(gt=0, strict=True)
    expected_released: str = Field(pattern=r'^\d{1,12}(?:\.\d{1,6})?$', max_length=25)
    quantity: str = Field(pattern=r'^\d{1,12}(?:\.\d{1,6})?$', max_length=25)
    reason: str = Field(min_length=1, max_length=1000)


class ReservationCaseRead(BaseModel):
    case_key: UUID
    version: int
    status: Literal['REQUESTED', 'APPROVED', 'REJECTED', 'CONSUMED']
    source_version: int
    reservation_key: UUID
    document_key: UUID
    line_key: UUID
    base_unit: str
    held_quantity: str
    released_before: str
    reason: str
    requestor_id: int
    reviewer_id: int | None
    review_reason: str | None
    requested_at: datetime


class ReleaseCaseRead(ReservationCaseRead):
    release_quantity: str


class ReservationSourceRead(BaseModel):
    reservation_key: UUID
    document_key: UUID
    line_key: UUID
    source_version: int
    product_id: int
    product_name: str
    location_id: int
    location_name: str
    branch_id: int
    branch_name: str
    base_unit: str
    held_quantity: str
    released_before: str
    remaining_quantity: str
    review_at: datetime
    deadline_version: int
    review_due: bool

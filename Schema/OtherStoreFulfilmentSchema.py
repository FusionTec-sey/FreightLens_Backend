"""Explicit review intent only; no client posting authority."""
from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from Schema.SalesReservationSchema import SalesDemandReference
from Schema.ReservationReallocationSchema import TargetHoldSummary


class OtherStoreCaseRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    operation_key: UUID
    source: SalesDemandReference
    assignment_version: int = Field(gt=0, strict=True)
    balance_id: int = Field(gt=0, strict=True)
    expected_stock_version: int = Field(gt=0, strict=True)
    quantity: str = Field(pattern=r'^\d{1,12}(?:\.\d{1,6})?$', max_length=25)
    input_unit: str = Field(min_length=1, max_length=32)
    review_at: AwareDatetime
    reason: str = Field(min_length=1, max_length=1000)


class OwnWorkingStoreRead(BaseModel):
    branch_id: int
    assignment_version: int
    counter_id: int | None


class OtherStoreCaseRead(BaseModel):
    case_key: UUID
    version: int
    status: Literal['REQUESTED', 'APPROVED', 'REJECTED', 'CONSUMED']
    source_version: int
    source: SalesDemandReference
    reason: str
    requestor_id: int
    reviewer_id: int | None
    review_reason: str | None
    requested_at: datetime
    selling_branch_id: int
    fulfilment_branch_id: int
    location_id: int
    balance_id: int
    stock_version: int
    product_id: int
    quantity: str
    base_unit: str
    input_quantity: str
    input_unit: str
    review_at: AwareDatetime
    existing_holds: TargetHoldSummary

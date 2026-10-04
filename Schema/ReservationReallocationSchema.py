from typing import Literal
from uuid import UUID
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from Schema.ReservationReleaseCaseSchema import ReleaseCaseRequest, ReservationCaseRead
from Schema.SalesReservationSchema import SalesDemandReference


class ReallocationCaseRequest(ReleaseCaseRequest):
    target: SalesDemandReference
    review_at: AwareDatetime


class TargetHoldSummary(BaseModel):
    count: int
    remaining: str


class ReallocationExecutionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    operation_key: UUID
    branch_version: int = Field(gt=0, strict=True)


class ReallocationExecutionContext(BaseModel):
    case_key: UUID
    branch_id: int
    branch_version: int


class ReallocationExecutionRead(BaseModel):
    operation_key: UUID
    case_key: UUID
    source_reservation_key: UUID
    target_reservation_key: UUID
    source_remaining: str
    target_remaining: str
    base_unit: str
    status: Literal['CONSUMED']
    replayed: bool


class ReallocationCaseRead(ReservationCaseRead):
    quantity: str
    target: SalesDemandReference
    target_review_at: AwareDatetime
    target_hold_snapshot: TargetHoldSummary | None = None

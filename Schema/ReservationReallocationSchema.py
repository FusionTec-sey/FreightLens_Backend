from pydantic import AwareDatetime, BaseModel
from Schema.ReservationReleaseCaseSchema import ReleaseCaseRequest, ReservationCaseRead
from Schema.SalesReservationSchema import SalesDemandReference


class ReallocationCaseRequest(ReleaseCaseRequest):
    target: SalesDemandReference
    review_at: AwareDatetime


class TargetHoldSummary(BaseModel):
    count: int
    remaining: str


class ReallocationCaseRead(ReservationCaseRead):
    quantity: str
    target: SalesDemandReference
    target_review_at: AwareDatetime
    target_hold_snapshot: TargetHoldSummary | None = None

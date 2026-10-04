from uuid import UUID
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from Schema.SalesReservationSchema import SalesDemandReference


class StoreAllocationRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    operation_key: UUID
    source: SalesDemandReference
    counter_key: UUID
    branch_version: int = Field(gt=0, strict=True)
    counter_version: int = Field(gt=0, strict=True)
    assignment_version: int = Field(gt=0, strict=True)
    quantity: str = Field(pattern=r'^\d{1,12}(?:\.\d{1,6})?$', max_length=25)
    input_unit: str = Field(min_length=1, max_length=32)
    review_at: AwareDatetime
    reason: str = Field(min_length=1, max_length=500)


class AllocatedHoldRead(BaseModel):
    operation_key: UUID
    reservation_key: UUID
    balance_id: int
    location_id: int
    quantity: str


class StoreAllocationRead(BaseModel):
    operation_key: UUID
    branch_id: int
    quantity: str
    base_unit: str
    reservations: list[AllocatedHoldRead]
    replayed: bool

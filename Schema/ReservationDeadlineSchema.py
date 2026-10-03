from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, AwareDatetime
from Schema.ReservationReleaseCaseSchema import ReservationCaseRead


class DeadlineRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    operation_key: UUID
    reservation_key: UUID
    expected_source_version: int = Field(gt=0, strict=True)
    expected_deadline_version: int = Field(ge=0, strict=True)
    expected_released: str = Field(pattern=r'^\d{1,12}(?:\.\d{1,6})?$', max_length=25)
    next_review_at: AwareDatetime
    reason: str = Field(min_length=1, max_length=1000)


class DeadlineCaseRead(ReservationCaseRead):
    deadline_version: int
    review_at: datetime
    next_review_at: datetime


class DeadlineApply(BaseModel):
    model_config = ConfigDict(extra='forbid')
    operation_key: UUID


class DeadlineApplied(BaseModel):
    reservation_key: UUID
    deadline_version: int
    review_at: datetime
    replayed: bool

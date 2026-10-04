"""Read-only local stock preview for saved sales demand."""
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator


class SalesAreaSuggestion(BaseModel):
    balance_id: int
    balance_version: int
    location_id: int
    location_name: str
    quantity: str


class SalesAreaPreviewLine(BaseModel):
    line_key: UUID
    product_id: int
    base_unit: str
    remaining_demand: str
    local_unreserved: str
    provisional_coverage: str
    shortfall: str
    tracked_for_review: str
    suggestions: list[SalesAreaSuggestion]


class SalesAreaPreview(BaseModel):
    document_key: UUID
    draft_version: int
    counter_key: UUID
    counter_version: int
    work_area_id: int
    work_area_name: str
    incomplete: bool
    reservation_ready: bool
    lines: list[SalesAreaPreviewLine]


class LocalDraftReserveRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    expected_draft_version: int = Field(gt=0, strict=True)
    line_key: UUID
    counter_key: UUID
    counter_version: int = Field(gt=0, strict=True)
    balance_id: int = Field(gt=0, strict=True)
    quantity: str = Field(max_length=25, pattern=r'^[0-9]{1,12}(?:\.[0-9]{1,6})?$')
    review_at: datetime
    reason: str = Field(min_length=1, max_length=500)

    @field_validator('review_at')
    @classmethod
    def aware_review(cls, value):
        if value.utcoffset() is None:
            raise ValueError('Review date needs a timezone')
        return value


class LocalDraftReserveReceipt(BaseModel):
    reservation_key: UUID
    balance_id: int
    version: int
    replayed: bool


class OtherAreaRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    operation_key: UUID
    document_key: UUID
    expected_draft_version: int = Field(gt=0, strict=True)
    line_key: UUID
    counter_key: UUID
    counter_version: int = Field(gt=0, strict=True)
    balance_id: int = Field(gt=0, strict=True)
    quantity: str = Field(max_length=25, pattern=r'^[0-9]{1,12}(?:\.[0-9]{1,6})?$')
    review_at: datetime
    reason: str = Field(min_length=1, max_length=500)

    @field_validator('review_at')
    @classmethod
    def aware_review(cls, value):
        if value.utcoffset() is None: raise ValueError('Review date needs a timezone')
        return value


class OtherAreaBalance(BaseModel):
    balance_id: int
    branch_id: int
    location_name: str
    available: str
    base_unit: str


class OtherAreaReserveReceipt(BaseModel):
    reservation_key: UUID
    balance_id: int
    version: int
    replayed: bool

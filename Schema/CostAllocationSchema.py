from uuid import UUID
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator
from Schema.InventoryValuationSchema import CostAllocationPreviewRequest, CostAllocationPreview


class CostAllocationSave(CostAllocationPreviewRequest):
    operation_key: UUID
    charge_reference: str = Field(min_length=1, max_length=160)
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator('charge_reference', 'reason')
    @classmethod
    def required_text(cls, value):
        if not value.strip(): raise ValueError('Explicit reference and reason required')
        return value.strip()


class CostAllocationSaved(BaseModel):
    proposal_key: UUID
    status: Literal['PROPOSED'] = 'PROPOSED'
    posting_enabled: Literal[False] = False
    replayed: bool


class CostAllocationSummary(BaseModel):
    proposal_key: UUID
    charge_reference: str
    total_scr: str
    basis: str
    created_at: datetime
    status: Literal['PROPOSED'] = 'PROPOSED'


class CostAllocationDetail(CostAllocationSummary):
    reason: str
    snapshot: CostAllocationPreview


class CostAllocationReviewRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    operation_key: UUID
    reason: str = Field(min_length=1, max_length=1000)


class CostAllocationCaseRead(BaseModel):
    case_key: UUID
    version: int
    status: Literal['REQUESTED', 'APPROVED', 'REJECTED', 'CONSUMED']
    source_version: int
    reason: str
    requestor_id: int
    creator_id: int
    reviewer_id: int | None
    review_reason: str | None
    requested_at: datetime
    charge_reference: str
    snapshot: CostAllocationPreview
    declaration_reason: str

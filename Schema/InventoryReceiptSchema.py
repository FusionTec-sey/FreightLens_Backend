"""Explicit source/location selection, not permission to post received stock."""
from pydantic import BaseModel, ConfigDict, Field, field_validator
from Schema.StockReclassificationSchema import ReclassificationBatch
from Schema.InventorySerialSchema import SerialOpening
from Schema.InventoryPolicySchema import InventoryPolicyConfig
from datetime import datetime
from uuid import UUID
from typing import Literal


class InventoryReceiptSource(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    receipt_id: int = Field(gt=0, strict=True)
    receipt_item_id: int = Field(gt=0, strict=True)
    branch_id: int = Field(gt=0, strict=True)
    location_id: int = Field(gt=0, strict=True)
    expected_policy_version: int = Field(gt=0, strict=True)


class InventoryReceiptManifest(BaseModel):
    """Base-unit physical classification; never inferred from overlapping claims."""
    model_config = ConfigDict(extra='forbid', frozen=True, str_strip_whitespace=True)
    source: InventoryReceiptSource
    on_hand: str = Field(pattern=r'^[0-9]{1,12}(?:\.[0-9]{1,6})?$')
    damaged: str = Field(pattern=r'^[0-9]{1,12}(?:\.[0-9]{1,6})?$')
    quarantined: str = Field(pattern=r'^[0-9]{1,12}(?:\.[0-9]{1,6})?$')
    reason: str = Field(min_length=1, max_length=500)
    batches: tuple[ReclassificationBatch, ...] = Field(default=(), max_length=1000)
    serials: SerialOpening | None = None


class ReceiptManifestCreate(InventoryReceiptManifest):
    operation_key: UUID

    @field_validator('operation_key')
    @classmethod
    def nonzero_operation_key(cls, value):
        if not value.int:
            raise ValueError('Operation key must be nonzero')
        return value


class ReceiptManifestSaved(BaseModel):
    manifest_key: UUID
    status: Literal['SAVED']
    replayed: bool = False
    physical_posting_enabled: Literal[False] = False


class ReceiptManifestSummary(BaseModel):
    manifest_key: UUID
    receipt_id: int
    receipt_item_id: int
    product_id: int
    branch_id: int
    location_id: int
    created_at: datetime
    created_by: int
    status: Literal['SAVED'] = 'SAVED'
    physical_posting_enabled: Literal[False] = False


class ReceiptBaseQuantities(BaseModel):
    received_quantity: str
    damaged_quantity: str
    incorrect_quantity: str


class ReceiptSourceSnapshot(BaseModel):
    org_id: int
    receipt_id: int
    receipt_item_id: int
    po_id: int
    po_item_id: int
    product_id: int
    posting_version: int
    submitted_at: datetime
    branch_id: int
    location_id: int
    unit: str
    received_quantity: str
    base_unit: str
    base_quantities: ReceiptBaseQuantities
    policy_version: int
    policy: InventoryPolicyConfig
    requires_condition_review: bool
    physical_posting_enabled: Literal[False] = False


class ReceiptManifestQuantities(BaseModel):
    on_hand: str
    damaged: str
    quarantined: str
    available: str


class ReceiptManifestPreview(BaseModel):
    source: ReceiptSourceSnapshot
    manifest: InventoryReceiptManifest
    quantities: ReceiptManifestQuantities
    condition_review_required: bool
    physical_posting_enabled: Literal[False] = False


class ReceiptManifestDetail(ReceiptManifestSummary):
    source: ReceiptSourceSnapshot
    manifest: InventoryReceiptManifest
    quantities: ReceiptManifestQuantities
    condition_review_required: bool
    historical_snapshot: Literal[True] = True


class ReceiptManifestReviewCase(BaseModel):
    case_key: UUID
    manifest_key: UUID
    version: int
    status: Literal['REQUESTED', 'APPROVED', 'REJECTED', 'CONSUMED']
    receipt_id: int
    receipt_item_id: int
    product_id: int
    branch_id: int
    location_id: int
    reason: str
    requestor_id: int
    reviewer_id: int | None = None
    review_reason: str | None = None
    requested_at: datetime
    physical_posting_enabled: Literal[False] = False

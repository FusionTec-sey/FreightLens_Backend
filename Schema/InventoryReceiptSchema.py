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


class ReceiptPostingRequest(BaseModel):
    """Stable execution intent; all cost and stock scope remains server-derived."""
    model_config = ConfigDict(extra='forbid', frozen=True, str_strip_whitespace=True)
    operation_key: UUID
    classification_case_key: UUID
    cost_case_key: UUID
    expected_valuation_version: int = Field(ge=0, strict=True)
    reason: str = Field(min_length=1, max_length=500)

    @field_validator('operation_key', 'classification_case_key', 'cost_case_key')
    @classmethod
    def nonzero_posting_key(cls, value):
        if not value.int:
            raise ValueError('Posting and reviewed-case keys must be nonzero')
        return value


class ReceiptPostingContext(BaseModel):
    manifest_key: UUID
    branch_id: int
    product_id: int
    cost_pool_id: int
    valuation_version: int
    physical_posting_enabled: Literal[True] = True


class ReceiptPostedMovement(BaseModel):
    balance_id: int
    version: int
    on_hand: str
    reserved: str
    available: str
    damaged: str
    quarantined: str
    batch_key: str | None = None


class ReceiptPostingRead(BaseModel):
    operation_key: UUID
    replayed: bool
    manifest_key: UUID
    classification_case_key: UUID
    cost_case_key: UUID
    status: Literal['POSTED_UNRECONCILED']
    valuation_ids: list[int]
    cost_pool_id: int
    product_id: int
    version: int
    pool_quantity: str
    pool_value_scr: str
    average_cost_scr: str
    movements: list[ReceiptPostedMovement]

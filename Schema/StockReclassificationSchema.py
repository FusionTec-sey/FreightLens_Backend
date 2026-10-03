"""Explicit proposal input; authoritative source quantities are never client input."""
from decimal import Decimal
from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field
from Schema.InventoryBatchSchema import StockBatchIdentity
from Schema.InventorySerialSchema import SerialOpening
from Schema.InventoryPolicySchema import InventoryPolicyConfig
from Services.inventory_quantity_service import QuantityBreakdown


class ReclassificationBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    identity: StockBatchIdentity
    on_hand: str = Field(pattern=r"^[0-9]{1,12}(?:\.[0-9]{1,6})?$")
    damaged: str = Field(default="0", pattern=r"^[0-9]{1,12}(?:\.[0-9]{1,6})?$")
    quarantined: str = Field(default="0", pattern=r"^[0-9]{1,12}(?:\.[0-9]{1,6})?$")

    def quantities(self):
        return QuantityBreakdown(Decimal(self.on_hand), damaged=Decimal(self.damaged),
                                 quarantined=Decimal(self.quarantined))


class ReclassificationProposalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    operation_key: UUID
    balance_id: int = Field(gt=0, strict=True)
    expected_balance_version: int = Field(gt=0, strict=True)
    expected_active_version: int = Field(gt=0, strict=True)
    expected_draft_version: int = Field(gt=0, strict=True)
    reason: str = Field(min_length=1, max_length=500)
    batches: tuple[ReclassificationBatch, ...] = Field(default=(), max_length=1000)
    serials: SerialOpening | None = None


class ReclassificationProposalSaved(BaseModel):
    proposal_key: UUID
    status: Literal["SAVED"]
    balance_id: int
    balance_version: int
    replayed: bool = False
    conversion_enabled: Literal[False] = False


class ReclassificationProposalSummary(BaseModel):
    proposal_key: UUID
    balance_id: int
    product_id: int
    branch_id: int
    location_id: int
    balance_version: int
    active_version: int
    draft_version: int
    target_tracking: Literal["BATCH", "SERIAL"]
    reason: str
    created_at: datetime
    created_by: int
    conversion_enabled: Literal[False] = False


class ReclassificationQuantities(BaseModel):
    on_hand: str
    reserved: str
    damaged: str
    quarantined: str


class ReclassificationSnapshot(BaseModel):
    product_id: int
    branch_id: int
    location_id: int
    balance_id: int
    balance_version: int
    active_version: int
    draft_version: int
    original_policy: InventoryPolicyConfig
    active_policy: InventoryPolicyConfig
    target_policy: InventoryPolicyConfig
    quantities: ReclassificationQuantities


class ReclassificationProposalDetail(ReclassificationProposalSummary):
    snapshot: ReclassificationSnapshot
    manifest: ReclassificationProposalCreate
    historical_snapshot: Literal[True] = True


class ReclassificationReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    operation_key: UUID
    reason: str = Field(min_length=1, max_length=1000)

from uuid import UUID
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from Schema.InventoryPolicySchema import InventoryPolicyConfig


class PolicyActivationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_key: UUID
    expected_active_version: int = Field(ge=0, strict=True)


class PolicyTransitionRead(BaseModel):
    product_id: int
    draft_version: int
    active_version: int
    changed_fields: list[str]
    blockers: list[str]
    route: Literal["INITIAL_REVIEW", "EMPTY_REVISION_REVIEW", "COMPATIBLE_REVISION_REVIEW", "BLOCKED", "NO_CHANGE"]
    advisory_only: Literal[True] = True
    active_config: InventoryPolicyConfig | None = None
    proposed_config: InventoryPolicyConfig | None = None


class PolicyActivationRead(BaseModel):
    product_id: int
    version: int
    draft_version: int | None
    status: Literal["NOT_ACTIVE", "ACTIVE"]
    config: InventoryPolicyConfig | None
    replayed: bool = False

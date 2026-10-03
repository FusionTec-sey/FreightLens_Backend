from pydantic import BaseModel, ConfigDict, Field
from Schema.InventoryLocationSchema import NamedLocationInput


class CostPoolCreate(NamedLocationInput):
    pass


class CostPoolRead(CostPoolCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    org_id: int
    is_active: bool


class BranchCostPoolAssign(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cost_pool_id: int = Field(gt=0, strict=True)


class BranchCostPoolRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    org_id: int
    branch_id: int
    cost_pool_id: int

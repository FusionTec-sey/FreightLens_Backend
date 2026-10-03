from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class UnitBarcodeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    operation_key: UUID
    expected_policy_version: int = Field(gt=0, strict=True)
    barcode: str = Field(min_length=1, max_length=100, pattern=r"^[!-~]+$")
    unit: str = Field(min_length=1, max_length=50)


class UnitBarcodeRead(BaseModel):
    id: int
    product_id: int
    policy_version: int
    barcode: str
    unit: str
    base_unit: str
    base_quantity: str
    eligible: bool
    retired: bool = False
    replayed: bool = False

from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator
from Schema.BranchSettingsSchema import BranchSettingsSave
from Schema.InventoryLocationSchema import LocationRead, LocationPage


class CounterConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)
    purpose: Literal["CHECKOUT", "COLLECTION", "BOTH"]
    is_enabled: bool = Field(default=False, strict=True)
    default_stock_location_id: int | None = Field(default=None, gt=0, strict=True)


class CounterSave(BranchSettingsSave):
    config: CounterConfig
    code: str = Field(min_length=1, max_length=32, pattern=r"^[A-Z0-9][A-Z0-9_-]{0,31}$")

    @field_validator("code", mode="before")
    @classmethod
    def normalize_code(cls, value):
        return value.strip().upper() if isinstance(value, str) else value


class CounterRead(BaseModel):
    id: int
    branch_id: int
    counter_key: UUID
    code: str
    version: int
    config: CounterConfig
    operational_activation: Literal[False] = False


class CounterStockAreaRead(LocationPage[LocationRead]):
    root: LocationRead | None
    counter_version: int
    counter_enabled: bool
    operational_activation: Literal[False] = False

from pydantic import BaseModel, ConfigDict, Field
from Schema.BranchSettingsSchema import BranchSettingsSave


class StaffStoreConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    branch_id: int = Field(gt=0, strict=True)
    counter_id: int | None = Field(default=None, gt=0, strict=True)
    is_enabled: bool = Field(strict=True)


class StaffStoreSave(BranchSettingsSave):
    config: StaffStoreConfig


class StaffStoreRead(BaseModel):
    user_id: int
    username: str
    version: int
    config: StaffStoreConfig | None = None
    branch_name: str | None = None

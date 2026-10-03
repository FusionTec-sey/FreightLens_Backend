from typing import Generic, Literal, TypeVar
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class NamedLocationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    code: str = Field(pattern=r"^[A-Z0-9][A-Z0-9_-]{0,31}$")
    name: str = Field(min_length=1, max_length=120)

    @field_validator("code", mode="before")
    @classmethod
    def normalize_code(cls, value):
        return value.strip().upper() if isinstance(value, str) else value


class BranchCreate(NamedLocationInput):
    kind: Literal["STORE", "WAREHOUSE"]
    notes: str | None = Field(default=None, max_length=1000)


class LocationCreate(NamedLocationInput):
    kind: Literal["SITE", "ZONE", "BIN"]
    parent_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def parent_required(self):
        if (self.kind == "SITE") != (self.parent_id is None):
            raise ValueError("Sites have no parent; zones and bins require a parent")
        return self


class BranchRead(BranchCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    org_id: int
    is_active: bool


class LocationRead(LocationCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    org_id: int
    branch_id: int
    is_active: bool


Row = TypeVar("Row")


class LocationPage(BaseModel, Generic[Row]):
    items: list[Row]
    total: int
    page: int
    pages: int
    limit: int

"""Serial identities are known before reservation; assignment occurs at handover."""
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SerialCondition = Literal["AVAILABLE", "DAMAGED", "QUARANTINED"]


class SerialOpeningItem(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)
    serial_key: UUID
    serial_number: str = Field(min_length=1, max_length=100)
    condition: SerialCondition

    @field_validator("serial_key")
    @classmethod
    def nonzero(cls, value):
        if not value.int:
            raise ValueError("A nonzero serial key is required")
        return value

    @field_validator("serial_number")
    @classmethod
    def printable(cls, value):
        if not value.isprintable():
            raise ValueError("Serial numbers cannot contain control characters")
        return value


class SerialOpening(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    items: tuple[SerialOpeningItem, ...] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def unique(self):
        if len({row.serial_key for row in self.items}) != len(self.items) or len({row.serial_number for row in self.items}) != len(self.items):
            raise ValueError("Serial keys and numbers must be unique within the opening")
        return self


class StockSerialRead(BaseModel):
    id: int
    serial_key: UUID
    serial_number: str
    condition: SerialCondition

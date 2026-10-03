"""Preparation only: these drafts do not activate stock tracking."""
from decimal import Decimal, Context, localcontext
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class UnitConversion(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    unit: str = Field(min_length=1, max_length=50)
    factor: Decimal = Field(gt=0, lt=1000000000, max_digits=17, decimal_places=8)

    @field_validator("factor", mode="before")
    @classmethod
    def exact_input(cls, value):
        if isinstance(value, (float, bool)):
            raise ValueError("Use a decimal string for the conversion factor")
        return value


class InventoryPolicyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    base_unit: str = Field(min_length=1, max_length=50)
    quantity_step: Literal["1", "0.1", "0.01", "0.001", "0.0001", "0.00001", "0.000001"]
    tracking: Literal["UNTRACKED", "BATCH", "SERIAL"]
    require_expiry: bool = False
    require_shade: bool = False
    require_calibre: bool = False
    conversions: list[UnitConversion] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def compatible_tracking(self):
        if self.tracking != "BATCH" and (self.require_expiry or self.require_shade or self.require_calibre):
            raise ValueError("Expiry, shade and calibre require batch tracking")
        if self.tracking == "SERIAL" and self.quantity_step != "1":
            raise ValueError("Serial-tracked stock requires whole base units")
        units = [self.base_unit.casefold()] + [row.unit.casefold() for row in self.conversions]
        if len(set(units)) != len(units):
            raise ValueError("Unit names must be unique, including the base unit")
        with localcontext(Context(prec=48)):
            for row in self.conversions:
                if row.factor % Decimal(self.quantity_step):
                    raise ValueError("Each conversion must be an exact multiple of the base quantity step")
        return self


class InventoryPolicySave(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=0, strict=True)
    config: InventoryPolicyConfig


class InventoryPolicyRead(BaseModel):
    product_id: int
    current_base_unit: str | None
    version: int
    status: Literal["NOT_CONFIGURED", "DRAFT"]
    config: InventoryPolicyConfig | None


class InventoryUnitPreview(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    config: InventoryPolicyConfig
    quantity: str = Field(min_length=1, max_length=30, pattern=r"^[0-9]+(?:\.[0-9]{1,6})?$")
    unit: str = Field(min_length=1, max_length=50)


class InventoryUnitPreviewRead(BaseModel):
    base_unit: str
    base_quantity: str
    quantity_step: str
    draft_only: Literal[True] = True

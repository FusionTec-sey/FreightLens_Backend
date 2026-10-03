"""Goods receipt input: quantities match the database's exact decimal scale."""
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Quantity = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2, allow_inf_nan=False)]


class ReceiptLineCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    po_item_id: int = Field(gt=0)
    packing_item_id: int | None = Field(default=None, gt=0)
    description: str = Field(min_length=1)
    expected_quantity: Quantity = Decimal("0")
    received_quantity: Quantity = Decimal("0")
    missing_quantity: Quantity = Decimal("0")
    excess_quantity: Quantity = Decimal("0")
    damaged_quantity: Quantity = Decimal("0")
    incorrect_quantity: Quantity = Decimal("0")
    unit: str = Field(default="PCS", min_length=1, max_length=50)
    condition_ok: bool = True
    notes: str | None = None
    photo_url: str | None = Field(default=None, max_length=500)


class ReceiptCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    po_id: int = Field(gt=0)
    receipt_number: str = Field(default="", max_length=100)
    received_date: date = Field(default_factory=date.today)
    packing_list_id: int | None = Field(default=None, gt=0)
    container_id: int | None = Field(default=None, gt=0)
    warehouse_location: str | None = Field(default=None, max_length=150)
    status: Literal["DRAFT", "SUBMITTED"] = "DRAFT"
    has_discrepancies: bool = False  # Accepted for compatibility; derived server-side.
    notes: str | None = None
    items: list[ReceiptLineCreate] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def unique_lines(self):
        ids = [item.po_item_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("Each purchase order item may occur only once per receipt")
        return self

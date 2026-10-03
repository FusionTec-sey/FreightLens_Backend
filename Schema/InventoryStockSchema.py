"""Read-only physical quantities. No costs, vendors or sale authorization."""
from datetime import datetime, date
from uuid import UUID
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, field_serializer


class StockBalanceRead(BaseModel):
    id: int
    product_id: int
    sku: str
    product_name: str
    product_status: str
    base_unit: str
    tracking_policy: Literal["UNTRACKED", "BATCH", "SERIAL"]
    batch_key: UUID | None
    batch_code: str | None
    batch_shade: str | None
    batch_calibre: str | None
    expires_on: date | None
    quantity_step: Decimal | None
    unit_policy_status: Literal["SNAPSHOTTED", "REVIEW_REQUIRED"]
    on_hand: Decimal
    reserved: Decimal
    available: Decimal
    damaged: Decimal
    quarantined: Decimal
    version: int
    updated_at: datetime

    @field_serializer("on_hand", "reserved", "available", "damaged", "quarantined")
    def exact_quantity(self, value):
        return format(value, ".6f")

    @field_serializer("quantity_step")
    def exact_step(self, value):
        return format(value, ".6f") if value is not None else None

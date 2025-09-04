from pydantic import BaseModel
from typing import Optional
from datetime import date
from decimal import Decimal
from decimal import Decimal

class ReportDetailsSchema(BaseModel):
    container_id: str
    # report_id: str
    report_date: date
    material_as_packing_list: str | None = None
    damage_goods: str | None = None
    comment: str | None = None
    value_of_damage_good: Decimal | None = None
    consignee: str | None = None

    class Config:
        from_attributes = True

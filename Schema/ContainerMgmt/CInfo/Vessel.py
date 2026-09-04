from pydantic import BaseModel
from datetime import date
from typing import Optional

class VessalSchema(BaseModel):
    id: int
    VessalNo: str
    # ArrivalOn: Optional[date]

    class Config:
         from_attributes = True

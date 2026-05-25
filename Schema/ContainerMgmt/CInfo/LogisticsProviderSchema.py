from pydantic import BaseModel
from typing import List, Optional

class LogisticsProviderResponseSchema(BaseModel):
    Id: int
    Name: Optional[str] = None
    ExcludingDays: int
    FreeDays: int
    ExcludingDaysList: List[str]

    class Config:
        from_attributes = True

class LogisticsProviderUpdateSchema(BaseModel):
    FreeDays: Optional[int] = None
    ExcludingDays: Optional[int] = None
    ExcludingDaysList: Optional[List[str]] = None

    class Config:
        from_attributes = True

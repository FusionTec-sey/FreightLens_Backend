from pydantic import BaseModel
from typing import List, Optional

class UserBase(BaseModel):
    username: str
    password: Optional[str] = None
    roles: Optional[List[int]] = None

class UserCreate(UserBase):
    password: str

class UserOut(UserBase):
    id: int
    roles: List[str] = []

    class Config:
        from_attributes = True

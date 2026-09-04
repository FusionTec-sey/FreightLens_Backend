from pydantic import BaseModel
from typing import List, Optional

class RoleBase(BaseModel):
    name: str
    permissions: Optional[List[int]] = []

class RoleCreate(RoleBase):
    pass

class RoleOut(RoleBase):
    id: int
    permissions: List[str] = []

    class Config:
        from_attributes = True

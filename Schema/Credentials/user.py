from pydantic import BaseModel, model_validator
from typing import List, Optional, Union

class UserBase(BaseModel):
    username: Optional[str] = None
    name: Optional[str] = None
    password: Optional[str] = None
    org_id: Optional[int] = None
    org_ids: Optional[List[int]] = None
    roles: Optional[List[Union[int, str]]] = None

    @model_validator(mode="before")
    @classmethod
    def set_username_and_name(cls, data):
        if isinstance(data, dict):
            if not data.get("username") and data.get("name"):
                data["username"] = data["name"]
            elif not data.get("name") and data.get("username"):
                data["name"] = data["username"]
        return data

class UserCreate(UserBase):
    password: str

class UserOut(UserBase):
    id: int
    roles: List[str] = []

    class Config:
        from_attributes = True

# schemas/status.py

from pydantic import BaseModel

class StatusSchema(BaseModel):
    name: str

    class Config:
        from_attributes = True

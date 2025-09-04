
from pydantic import BaseModel

class SupplierSchema(BaseModel):
    supplier_id: int
    Name: str | None = None
    address: str | None = None
    email: str | None = None

    class Config:
        from_attributes = True

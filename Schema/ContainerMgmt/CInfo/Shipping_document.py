
from pydantic import BaseModel

class ShippingDocumentSchema(BaseModel):
    doc_id: int
    doc_type: str | None = None

    class Config:
        from_attributes = True

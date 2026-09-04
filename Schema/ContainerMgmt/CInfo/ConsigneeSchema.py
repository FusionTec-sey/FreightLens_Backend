from pydantic import BaseModel

class ConsigneeSchema(BaseModel):
    consignee_id: int
    consignee_name: str | None = None

    class Config:
        from_attributes = True

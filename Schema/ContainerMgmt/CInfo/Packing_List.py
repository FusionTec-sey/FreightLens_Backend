from pydantic import BaseModel

class PackingListSchema(BaseModel):
    Container_id: int
    Packing_List: str | None = None

    class Config:
        from_attributes = True
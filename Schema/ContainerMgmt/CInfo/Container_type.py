from pydantic import BaseModel

class ContainerTypeSchema(BaseModel):
    # type_id: int
    type: str | None = None

    class Config:
        from_attributes = True

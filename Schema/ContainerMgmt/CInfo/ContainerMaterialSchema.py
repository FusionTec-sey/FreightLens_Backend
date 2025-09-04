from pydantic import BaseModel

class ContainerProductSchema(BaseModel):
    # ContainerId: int
    Id: int

    class Config:
        from_attributes = True
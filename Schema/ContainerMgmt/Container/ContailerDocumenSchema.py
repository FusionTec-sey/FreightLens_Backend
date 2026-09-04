from pydantic import BaseModel
from enum import Enum


class DocType(str, Enum):
    AD = "AD"
    ED = "ED"
    D = "D"


class ContainerDocumentSchema(BaseModel):
    docs_id: int
    path: str
    Type: DocType  # Add the enum field

    class Config:
        from_attributes = True
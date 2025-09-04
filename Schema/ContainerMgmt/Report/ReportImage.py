from pydantic import BaseModel

class ReportImage(BaseModel):
    Container_no: str
    Image: str

    class Config:
        from_attributes = True

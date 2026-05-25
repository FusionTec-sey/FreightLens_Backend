from pydantic import BaseModel, Field, ValidationError
from typing import Optional, List, Literal
from datetime import datetime, date
from fastapi import UploadFile

from .ContailerDocumenSchema import ContainerDocumentSchema
from .BillOfLandingSchema import BillOfLandingSchema
from ..CInfo.ContainerMaterialSchema import ContainerProductSchema
from Model.containermgmt.Container import ContainerDetails


class ContainerDetailsSchema(BaseModel):
    container_id: int = Field(..., alias="Container_ID")
    container_no: str

    in_bound: Optional[datetime]
    empty_date: Optional[date]
    out_bound: Optional[datetime]
    unloaded_at_port: Optional[date]
    note: Optional[str]
    tax: Optional[int]
    PONo: Optional[str]
    BillOfLanding: Optional[str]
    FreeDays: Optional[int] = None

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    created_by_name: Optional[str] = None
    updated_by_name: Optional[str] = None

    # Only human-readable display names
    state: Optional[str] = None
    containerType: Optional[str] = None
    location: Optional[str] = None

    # Related data
    documents: List[ContainerDocumentSchema] = []
    materials: List[ContainerProductSchema] = []
    bill_of_landing: Optional[BillOfLandingSchema] = None

    # Hidden ORM relationships (for internal use only)
    status_rel: Optional[object] = Field(None, exclude=True)
    type_rel: Optional[object] = Field(None, exclude=True)
    emptied_at_rel: Optional[object] = Field(None, exclude=True)
    created_by_user: Optional[object] = Field(None, exclude=True)
    updated_by_user: Optional[object] = Field(None, exclude=True)

    class Config:
        from_attributes = True
        populate_by_name = True

    @classmethod
    def from_orm_flat(cls, obj: ContainerDetails) -> "ContainerDetailsSchema":
        schema = cls.model_validate(obj)

        if obj.status_rel:
            schema.state = obj.status_rel.name
        if obj.type_rel:
            schema.containerType = obj.type_rel.type
        if obj.emptied_at_rel:
            schema.location = obj.emptied_at_rel.venue
        
        if obj.created_by_user:
            schema.created_by_name = obj.created_by_user.username
        if obj.updated_by_user:
            schema.updated_by_name = obj.updated_by_user.username

        if obj.bill_of_landing:
            schema.bill_of_landing = BillOfLandingSchema.from_orm_flat(obj.bill_of_landing)

        if obj.created_by_user:
            schema.created_by_name = obj.created_by_user.username
        if obj.updated_by_user:
            schema.updated_by_name = obj.updated_by_user.username

        
        return schema


class BillOfLandingUpdateSchema(BaseModel):
    
    Vessel: Optional[int] = None 
    Provider: Optional[int] = None
    Consignee: Optional[int] = None
    Supplier: Optional[int] = None
    Doc: Optional[int] = None
    
    ArrivalDate: Optional[datetime] = None
    FreeDays: Optional[int] = None
    status: Optional[int] = None
    # note: Optional[str]

# Optional: Schema for Material associations
class MaterialEntrySchema(BaseModel):
    MaterialId: int
    # quantity: Optional[float] = None  # or any other related fields

# Main schema to update a container
class ContainerUpdateSchema(BaseModel):
    # container_id: int
    container_no: Optional[str] = None
    # arrival_date: Optional[date]
    in_bound: Optional[datetime] = None
    empty_date: Optional[date] = None
    out_bound: Optional[datetime] = None
    unloaded_at_port: Optional[date] = None
    note: Optional[str] = None
    tax: Optional[int] = None
    PONo: Optional[str] = None
    FreeDays: Optional[int] = None
    
    # tax: Optional[int]
    # note: Optional[str]
    status: Optional[int] = None
    type: Optional[int] = None
    emptied_at: Optional[int] = None
    # Nested updates
    materials: Optional[List[int]] = None
    bill_of_landing: Optional[BillOfLandingUpdateSchema] = None

    
    # remove_doc_ids: Optional[List[int]] = None
    
    # new_docs: Optional[List[UploadFile]] = None
    # inboundBlob : Optional[List[UploadFile]] = None
    # emptyBlob: Optional[List[UploadFile]] = None



class BillOfLandingCreateSchema(BaseModel):
    BillOfLanding: str  # required
    Vessel: Optional[int] = None 
    Provider: Optional[int] = None
    Consignee: Optional[int] = None
    Supplier: Optional[int] = None
    Doc: Optional[int] = None
    
    ArrivalDate: Optional[datetime] = None
    FreeDays: Optional[int] = None


class ContainerCreateSchema(BaseModel):
    container_no: str = Field(..., description="Container number is required")
    bill_of_landing: Optional[BillOfLandingCreateSchema]  = None # required
    in_bound: Optional[datetime] = None
    empty_date: Optional[date] = None
    out_bound: Optional[datetime] = None
    unloaded_at_port: Optional[date] = None
    note: Optional[str] = None
    tax: Optional[int] = None
    PONo: Optional[str] = None
    FreeDays: Optional[int] = None
    
    # tax: Optional[int]
    # note: Optional[str]
    status: Optional[int] = None
    type: Optional[int] = None
    emptied_at: Optional[int] = None
    materials: Optional[List[int]] = []   


class ContainerListResponse(BaseModel):
    total_count: int
    data: List[dict]
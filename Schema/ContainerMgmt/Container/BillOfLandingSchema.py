from pydantic import BaseModel, Field
from datetime import datetime, date
from typing import Optional, List
# from .ContainerDetailsSchema import ContainerDetailsSchemaWithBl
from Model.containermgmt.Container import ContainerDetails

from .ContailerDocumenSchema import ContainerDocumentSchema
from ..CInfo.ContainerMaterialSchema import ContainerProductSchema

class ContainerCreateSchema(BaseModel):
    container_no: str
    in_bound: Optional[datetime] = None
    out_bound: Optional[datetime] = None
    empty_date: Optional[date] = None
    unloaded_at_port: Optional[date] = None
    note: Optional[str] = None
    tax: Optional[int] = None
    PONo: Optional[str] = None
    type: Optional[int] = None
    status: Optional[int] = None
    emptied_at: Optional[int] = None

class BillOfLandingInSchema(BaseModel):
    BillOfLanding: str
    Consignee: Optional[int] = None
    Vessel: Optional[int] = None
    ArrivalDate: datetime
    Doc: Optional[int] = None
    Supplier: Optional[int] = None
    Provider: Optional[int] = None
    FreeDays: Optional[int] = None
    status: Optional[int] = None
    new_containers: List[ContainerCreateSchema] = []


class BillOfLandingSchema(BaseModel):
    BillOfLanding: str
    # Consignee: Optional[int]
    # Vessel: Optional[int]
    ArrivalDate: Optional[datetime]
    # Doc: Optional[int]
    # Supplier: Optional[int]
    # Provider: Optional[int]
    FreeDays: Optional[int] = None
    status: Optional[int] = None

    # Related Display Names
    consignee_name: Optional[str] = None
    vessel_name: Optional[str] = None
    supplier_name: Optional[str] = None
    provider_name: Optional[str] = None
    Doc_name: Optional[str] = None

    class Config:
        from_attributes = True

    @classmethod
    def from_orm_flat(cls, obj):
        schema = cls.model_validate(obj)
        if obj.consignee_rel:
            schema.consignee_name = obj.consignee_rel.consignee_name
        if obj.vessel_rel:
            schema.vessel_name = obj.vessel_rel.VessalNo
        if obj.supplier_rel:
            schema.supplier_name = obj.supplier_rel.name
        if obj.provider_rel:
            schema.provider_name = obj.provider_rel.Name
        if obj.doc_rel:
            schema.Doc_name = obj.doc_rel.doc_type
        return schema

class ContainerDetailsSchemaWithBl(BaseModel):
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

    # Only human-readable display names
    state: Optional[str] = None
    containerType: Optional[str] = None
    location: Optional[str] = None

    # Related data
    documents: List[ContainerDocumentSchema] = []
    materials: List[ContainerProductSchema] = []
    # bill_of_landing: Optional[BillOfLandingSchema] = None

    # Hidden ORM relationships (for internal use only)
    status_rel: Optional[object] = Field(None, exclude=True)
    type_rel: Optional[object] = Field(None, exclude=True)
    emptied_at_rel: Optional[object] = Field(None, exclude=True)

    class Config:
        from_attributes = True
        populate_by_name = True

    @classmethod
    def from_orm_flat(cls, obj: ContainerDetails) -> "ContainerDetailsSchemaWithBl":
        schema = cls.model_validate(obj)

        if obj.status_rel:
            schema.state = obj.status_rel.name
        if obj.type_rel:
            schema.containerType = obj.type_rel.type
        if obj.emptied_at_rel:
            schema.location = obj.emptied_at_rel.venue


        
        return schema


class BillOfLandingWithContainersSchema(BaseModel):
    BillOfLanding: str
    # Consignee: Optional[int]
    # Vessel: Optional[int]
    ArrivalDate: Optional[datetime]
    # Doc: Optional[int]
    # Supplier: Optional[int]
    # Provider: Optional[int]
    FreeDays: Optional[int] = None
    status: Optional[int] = None

    # Related Display Names
    consignee_name: Optional[str] = None
    vessel_name: Optional[str] = None
    supplier_name: Optional[str] = None
    provider_name: Optional[str] = None
    Doc_name: Optional[str] = None
    containers: List[ContainerDetailsSchemaWithBl] = []
    
    class Config:
        from_attributes = True

    @classmethod
    def from_orm_flat(cls, obj):
        schema = cls.model_validate(obj)
        if obj.consignee_rel:
            schema.consignee_name = obj.consignee_rel.consignee_name
        if obj.vessel_rel:
            schema.vessel_name = obj.vessel_rel.VessalNo
        if obj.supplier_rel:
            schema.supplier_name = obj.supplier_rel.name
        if obj.provider_rel:
            schema.provider_name = obj.provider_rel.Name
        if obj.doc_rel:
            schema.Doc_name = obj.doc_rel.doc_type
        return schema

class BillOfLandingListResponse(BaseModel):
    total_count: int
    data: List[BillOfLandingWithContainersSchema]
    

class BillOfLandingUpdateOnlySchema(BaseModel):
    Consignee: Optional[int] = None
    Vessel: Optional[int] = None
    ArrivalDate: Optional[datetime] = None
    Doc: Optional[int] = None
    Supplier: Optional[int] = None
    Provider: Optional[int] = None
    FreeDays: Optional[int] = None
    status: Optional[int] = None
    
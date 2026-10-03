from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field
from Schema.CostChargeReviewSchema import CostChargeDeclaration
from Schema.CostAllocationSchema import CostAllocationCaseRead


class EvidenceRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    operation_key: UUID
    reason: str = Field(min_length=1, max_length=1000)
    declaration: CostChargeDeclaration


class SupplierChoice(BaseModel):
    id: int
    label: str


class DocumentChoice(BaseModel):
    id: UUID
    label: str
    doc_type: str


class EvidenceCaseRead(CostAllocationCaseRead):
    declaration: CostChargeDeclaration
    supplier_name: str
    documents: list[DocumentChoice]

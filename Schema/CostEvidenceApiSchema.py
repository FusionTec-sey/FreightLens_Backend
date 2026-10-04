from uuid import UUID
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
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


class ChargeStreamVersion(BaseModel):
    model_config = ConfigDict(extra='forbid')
    product_id: int = Field(gt=0, strict=True)
    version: int = Field(gt=0, strict=True)


class ChargePostingRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    operation_key: UUID
    streams: list[ChargeStreamVersion] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def distinct_streams(self):
        if not self.operation_key.int or len({row.product_id for row in self.streams}) != len(self.streams):
            raise ValueError('Nonzero operation and distinct product streams required')
        return self


class ChargePostingContext(BaseModel):
    case_key: UUID
    proposal_key: UUID
    pool_id: int
    streams: list[ChargeStreamVersion]


class ChargePostingRead(BaseModel):
    operation_key: UUID
    case_key: UUID
    proposal_key: UUID
    valuation_ids: list[int]
    status: Literal['UNRECONCILED']
    replayed: bool

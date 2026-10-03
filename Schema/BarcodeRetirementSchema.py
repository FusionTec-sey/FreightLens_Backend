from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field
from Schema.ManagerCaseSchema import PolicyCaseRead


class BarcodeRetirementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    operation_key: UUID
    barcode_id: int = Field(gt=0, strict=True)
    expected_source_version: int = Field(ge=1, le=1, strict=True)
    reason: str = Field(min_length=1, max_length=1000)


class BarcodeRetirementApply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_key: UUID
    expected_source_version: int = Field(ge=1, le=1, strict=True)


class BarcodeRetirementRead(BaseModel):
    barcode_id: int
    retired: Literal[True]
    replayed: bool = False


class BarcodeRetirementCaseRead(PolicyCaseRead):
    # Same audited request/decision metadata, but no fabricated policy config.
    config: dict
    kind: Literal["BARCODE_RETIREMENT"] = "BARCODE_RETIREMENT"

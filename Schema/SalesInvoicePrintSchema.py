"""Exact commands and safe reads for immutable sales invoice printing."""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _key(value: UUID) -> UUID:
    if value.int == 0:
        raise ValueError("UUID must be nonzero")
    return value


class SalesInvoicePrintRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_key: UUID
    operation_key: UUID
    artifact_key: UUID
    invoice_key: UUID
    kind: Literal["ORIGINAL", "COPY"]
    expected_template_id: int | None = Field(default=None, gt=0)
    expected_template_version_id: int | None = Field(default=None, gt=0)
    source_artifact_key: UUID | None = None

    @field_validator("job_key", "operation_key", "artifact_key", "invoice_key")
    @classmethod
    def valid_key(cls, value):
        return _key(value)

    @model_validator(mode="after")
    def valid_source(self):
        if self.kind == "ORIGINAL" and self.source_artifact_key is not None:
            raise ValueError("Original printing cannot name a source artifact")
        if self.kind == "ORIGINAL" and (
                self.expected_template_id is None or self.expected_template_version_id is None):
            raise ValueError("Original printing requires the exact selected template version")
        if self.kind == "COPY" and self.source_artifact_key is None:
            raise ValueError("COPY printing requires the immutable original artifact")
        if self.kind == "COPY" and (
                self.expected_template_id is not None or self.expected_template_version_id is not None):
            raise ValueError("COPY printing reuses the original template snapshot")
        if self.source_artifact_key is not None:
            _key(self.source_artifact_key)
        return self


class SalesInvoicePrintTransition(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    operation_key: UUID
    expected_version: int = Field(gt=0)
    outcome: Literal["PRINTED", "FAILED"]
    note: str = Field(min_length=1, max_length=1000)
    failure_code: str | None = Field(default=None, min_length=1, max_length=50, pattern=r"^[A-Z0-9_]+$")

    @field_validator("operation_key")
    @classmethod
    def valid_operation(cls, value):
        return _key(value)

    @model_validator(mode="after")
    def failure_requires_code(self):
        if (self.outcome == "FAILED") != (self.failure_code is not None):
            raise ValueError("FAILED needs a failure code; PRINTED cannot include one")
        return self


class SalesInvoicePrintHandoff(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_key: UUID
    expected_version: int = Field(gt=0)

    @field_validator("operation_key")
    @classmethod
    def valid_operation(cls, value):
        return _key(value)


class SalesInvoiceArtifactRead(BaseModel):
    artifact_key: UUID
    invoice_key: UUID
    template_id: int
    template_version_id: int
    artifact_kind: Literal["ORIGINAL", "COPY"]
    copy_number: int
    source_artifact_key: UUID | None
    pdf_sha256: str
    file_size: int
    created_at: datetime


class SalesInvoicePrintEventRead(BaseModel):
    sequence: int
    from_status: str | None
    to_status: Literal["READY", "UNCERTAIN", "PRINTED", "FAILED"]
    note: str
    created_at: datetime
    created_by: int


class SalesInvoicePrintJobRead(BaseModel):
    job_key: UUID
    artifact: SalesInvoiceArtifactRead
    status: Literal["READY", "UNCERTAIN", "PRINTED", "FAILED"]
    version: int
    handed_off_at: datetime | None
    resolved_at: datetime | None
    resolved_by: int | None
    failure_code: str | None
    resolution_note: str | None
    events: list[SalesInvoicePrintEventRead]


class SalesInvoicePrintResult(BaseModel):
    job: SalesInvoicePrintJobRead
    replayed: bool


class SalesInvoicePrintOptions(BaseModel):
    invoice_key: UUID
    invoice_number: str
    template_id: int
    template_version_id: int
    template_name: str
    original_artifact: SalesInvoiceArtifactRead | None


class SalesInvoicePrintJobPage(BaseModel):
    items: list[SalesInvoicePrintJobRead]
    page: int
    pages: int
    limit: int
    total: int

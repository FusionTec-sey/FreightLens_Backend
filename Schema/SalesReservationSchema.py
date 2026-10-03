from uuid import UUID, uuid5
from pydantic import BaseModel, ConfigDict, Field, field_validator


class SalesDemandReference(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    document_key: UUID
    line_key: UUID
    version: int = Field(gt=0, strict=True)

    @field_validator('document_key', 'line_key')
    @classmethod
    def nonzero(cls, value):
        if not value.int: raise ValueError('Nonzero source identities required')
        return value

    def stock_source_key(self):
        # Stable across revisions, distinct for equal line UUIDs in other drafts.
        return uuid5(self.document_key, f'sales-demand-line-v1:{self.line_key}')

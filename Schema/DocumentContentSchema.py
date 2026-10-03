"""Internal storage result, never accepted as public evidence input."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class DocumentContentFingerprint(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    policy: Literal['blob-sha256-v1']
    bucket: str = Field(min_length=1, max_length=255)
    object_key: str = Field(min_length=1, max_length=1024)
    version_id: str = Field(min_length=1, max_length=1024)
    size: int = Field(gt=0, strict=True)
    sha256: str = Field(pattern=r'^[a-f0-9]{64}$')

    @field_validator('bucket', 'object_key', 'version_id')
    @classmethod
    def explicit_identity(cls, value):
        if not value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError('Explicit storage identity required')
        return value

    @field_validator('version_id')
    @classmethod
    def versioned(cls, value):
        if value == 'null': raise ValueError('Unversioned evidence is not eligible')
        return value

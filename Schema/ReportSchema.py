"""
Schema/ReportSchema.py
Pydantic schemas for the Customer-Configurable Report & Print Template System.
"""
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID


class ReportTemplateVersionBase(BaseModel):
    html_content: str
    css_content: Optional[str] = None
    header_html: Optional[str] = None
    footer_html: Optional[str] = None
    changelog: Optional[str] = None


class ReportTemplateVersionCreate(ReportTemplateVersionBase):
    pass


class ReportTemplateVersionOut(ReportTemplateVersionBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    template_id: int
    version_number: int
    status: str
    created_at: Optional[datetime] = None
    created_by: Optional[int] = None


class ReportTemplateBase(BaseModel):
    name: str = Field(..., max_length=120)
    description: Optional[str] = None
    category: str = Field(..., max_length=50, description="LOGISTICS, ORDERS, CROSS_MODULE, etc.")
    resolver_key: str = Field(..., max_length=60)
    entity_type: Optional[str] = Field(None, max_length=60)
    page_size: Optional[str] = Field("A4", max_length=20)
    orientation: Optional[str] = Field("portrait", max_length=20)
    is_active: Optional[bool] = True


class ReportTemplateCreate(ReportTemplateBase):
    slug: str = Field(..., max_length=60, pattern=r"^[a-z0-9_-]+$")
    initial_version: Optional[ReportTemplateVersionCreate] = None


class ReportTemplateClone(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    description: Optional[str] = None


class ReportTemplateUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=120)
    description: Optional[str] = None
    category: Optional[str] = Field(None, max_length=50)
    resolver_key: Optional[str] = Field(None, max_length=60)
    entity_type: Optional[str] = Field(None, max_length=60)
    page_size: Optional[str] = Field(None, max_length=20)
    orientation: Optional[str] = Field(None, max_length=20)
    is_active: Optional[bool] = None


class ReportTemplateOut(ReportTemplateBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    is_system: bool
    active_version: Optional[int] = None
    org_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ReportTemplateDetailOut(ReportTemplateOut):
    active_version_data: Optional[ReportTemplateVersionOut] = None
    versions: Optional[List[ReportTemplateVersionOut]] = None


class ReportTemplatePaginatedResponse(BaseModel):
    items: List[ReportTemplateOut]
    total: int
    page: int
    pages: int
    limit: int


class ReportRenderRequest(BaseModel):
    template_id: Optional[int] = None
    template_slug: Optional[str] = None
    entity_type: Optional[str] = None
    entity_id: int
    format: Optional[str] = Field("pdf", description="'pdf' or 'html'")
    params: Optional[Dict[str, Any]] = None


class ReportPreviewRequest(BaseModel):
    template_id: Optional[int] = None
    template_slug: Optional[str] = None
    # For live editor preview without saving:
    html_content: Optional[str] = None
    css_content: Optional[str] = None
    header_html: Optional[str] = None
    footer_html: Optional[str] = None
    resolver_key: Optional[str] = None
    entity_id: Optional[int] = None
    params: Optional[Dict[str, Any]] = None


class ReportValidateRequest(BaseModel):
    html_content: str
    css_content: Optional[str] = None
    header_html: Optional[str] = None
    footer_html: Optional[str] = None
    resolver_key: Optional[str] = None


class ReportValidateResponse(BaseModel):
    is_valid: bool
    errors: List[str] = []
    warnings: List[str] = []


class ResolverFieldMeta(BaseModel):
    type: str
    description: Optional[str] = None
    restricted: bool = False
    permission: Optional[str] = None
    example: Optional[Any] = None
    item_fields: Optional[Dict[str, Any]] = None


class ResolverSchemaOut(BaseModel):
    resolver_key: str
    entity_type: Optional[str] = None
    category: str
    description: Optional[str] = None
    fields: Dict[str, Any]
    sample_context: Optional[Dict[str, Any]] = None


class ReportRenderJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    template_id: int
    entity_type: Optional[str] = None
    entity_id: int
    status: str
    error_message: Optional[str] = None
    download_url: Optional[str] = None
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

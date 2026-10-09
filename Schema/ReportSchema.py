"""
Schema/ReportSchema.py
Pydantic schemas for the Customer-Configurable Report & Print Template System.
"""
from pydantic import AliasChoices, BaseModel, Field, ConfigDict, field_validator
from typing import Annotated, Optional, List, Dict, Any, Literal, Union
from datetime import datetime


class ReportTemplateVersionBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

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


class TabularColumnLayout(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(..., min_length=1, max_length=100)
    label: Optional[str] = Field(None, max_length=120)
    visible: bool = True
    align: Literal["left", "center", "right"] = "left"
    width: Optional[str] = Field(None, max_length=30)
    overflow_mode: Literal["wrap", "truncate"] = "wrap"
    format: Optional[str] = Field(None, max_length=40)


class TabularLayout(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    columns: List[TabularColumnLayout] = []
    group_by: Optional[str] = Field(None, max_length=100, validation_alias=AliasChoices("group_by", "groupBy"))
    show_subtotals: bool = Field(True, validation_alias=AliasChoices("show_subtotals", "showSubtotals"))
    show_grand_total: bool = Field(True, validation_alias=AliasChoices("show_grand_total", "showGrandTotal"))
    sort_by: Optional[str] = Field(None, max_length=100, validation_alias=AliasChoices("sort_by", "sortBy"))
    sort_order: Literal["asc", "desc"] = Field("asc", validation_alias=AliasChoices("sort_order", "sortOrder"))
    date_preset: Optional[str] = Field(None, max_length=40, validation_alias=AliasChoices("date_preset", "datePreset"))
    supplier_ids: List[int] = Field(default_factory=list, validation_alias=AliasChoices("supplier_ids", "selectedSuppliers"))
    vessel_ids: List[int] = Field(default_factory=list, validation_alias=AliasChoices("vessel_ids", "selectedVessels"))
    venue_ids: List[int] = Field(default_factory=list, validation_alias=AliasChoices("venue_ids", "selectedVenues"))
    search: Optional[str] = Field(None, max_length=200, validation_alias=AliasChoices("search", "searchTerm"))


class ReportPaperSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    page_size: Literal["A4", "A3", "LETTER", "LEGAL", "CUSTOM"] = Field("A4", validation_alias=AliasChoices("page_size", "pageSize"))
    orientation: Literal["portrait", "landscape"] = "portrait"
    margin_preset: Optional[str] = Field(None, max_length=30, validation_alias=AliasChoices("margin_preset", "marginPreset"))
    margin_top: str = "12mm"
    margin_bottom: str = "12mm"
    margin_left: str = "10mm"
    margin_right: str = "10mm"
    repeat_header: bool = Field(True, validation_alias=AliasChoices("repeat_header", "repeatHeaderOnBreak"))
    break_per_group: bool = Field(False, validation_alias=AliasChoices("break_per_group", "pageBreakPerGroup"))
    avoid_row_split: bool = Field(True, validation_alias=AliasChoices("avoid_row_split", "avoidRowSplit"))
    sheet_per_group: bool = Field(False, validation_alias=AliasChoices("sheet_per_group", "sheetPerGroup"))
    alternate_row_banding: bool = Field(True, validation_alias=AliasChoices("alternate_row_banding", "alternateRowBanding"))

    @field_validator("margin_top", "margin_bottom", "margin_left", "margin_right")
    @classmethod
    def validate_margin(cls, value: str) -> str:
        import re

        value = value.strip().lower()
        if not re.fullmatch(r"\d+(?:\.\d+)?(?:mm|cm|in|pt)", value):
            raise ValueError("margin must be a positive CSS length using mm, cm, in, or pt")
        return value


class ReportTemplateBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., max_length=120)
    description: Optional[str] = None
    category: Optional[str] = Field(None, max_length=50, description="Derived from resolver on create")
    resolver_key: str = Field(..., max_length=60)
    entity_type: Optional[str] = Field(None, max_length=60, description="Derived from resolver on create")
    template_type: Optional[str] = Field("DOCUMENT", max_length=30, description="DOCUMENT or OPERATIONAL_TABULAR")
    table_config: Optional[TabularLayout] = None
    paper_settings: Optional[ReportPaperSettings] = None
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
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, max_length=120)
    description: Optional[str] = None
    category: Optional[str] = Field(None, max_length=50)
    resolver_key: Optional[str] = Field(None, max_length=60)
    entity_type: Optional[str] = Field(None, max_length=60)
    template_type: Optional[str] = Field(None, max_length=30)
    table_config: Optional[TabularLayout] = None
    paper_settings: Optional[ReportPaperSettings] = None
    page_size: Optional[str] = Field(None, max_length=20)
    orientation: Optional[str] = Field(None, max_length=20)
    is_active: Optional[bool] = None


class ReportTemplateOut(ReportTemplateBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    is_system: bool
    active_version_number: Optional[int] = None
    org_id: Optional[int] = None
    template_type: Optional[str] = "DOCUMENT"
    active_org_ids: Optional[List[int]] = None
    is_active_for_org: Optional[bool] = None
    is_default_for_org: bool = False
    default_options: Dict[str, Any] = Field(default_factory=dict)
    table_config: Optional[TabularLayout] = None
    paper_settings: Optional[ReportPaperSettings] = None
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


def _numeric_entity_ids_stay_integers(value):
    """Keep a numeric identifier an int, as it was before text ids were allowed.

    Screens that read the id from the URL hand over a string ("123"), and the
    smart union would keep it one. psycopg2 compares that to an integer column
    happily, but the resolvers are typed int and another driver would not, so the
    old behaviour is preserved and only genuinely non-numeric ids stay text.
    """
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return value


class ReportRenderRequest(BaseModel):
    template_id: Optional[int] = None
    template_slug: Optional[str] = None
    entity_type: Optional[str] = None
    # Bills of Lading and containers are addressed by their business numbers
    # (e.g. "MEDU1234567"), so the identifier may be text as well as an integer.
    # max_length sits on the str member, not the union: on the union Pydantic
    # applies it to integers too and every numeric render fails with a 500.
    entity_id: Optional[Union[int, Annotated[str, Field(min_length=1, max_length=100)]]] = None
    format: Optional[str] = Field("pdf", description="'pdf' or 'html'")
    params: Optional[Dict[str, Any]] = None
    _coerce_entity_id = field_validator("entity_id", mode="before")(
        _numeric_entity_ids_stay_integers
    )



class OrgPrintProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    legal_name: Optional[str] = Field(None, max_length=255)
    address: Optional[str] = Field(None, max_length=2000)
    tax_id: Optional[str] = Field(None, max_length=100)
    contact_email: Optional[str] = Field(None, max_length=255)
    contact_phone: Optional[str] = Field(None, max_length=100)
    logo_asset_key: Optional[str] = Field(None, max_length=500)
    stamp_asset_key: Optional[str] = Field(None, max_length=500)
    signature_asset_key: Optional[str] = Field(None, max_length=500)
    bank_details: Dict[str, Any] = Field(default_factory=dict)
    default_terms: Dict[str, Any] = Field(default_factory=dict)
    brand_color: Optional[str] = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    font_family: Optional[str] = Field(None, max_length=100)
    locale: str = Field("en-SC", min_length=2, max_length=20)
    timezone: str = Field("Indian/Mahe", min_length=3, max_length=100)


class OrgPrintProfileOut(OrgPrintProfileUpdate):
    model_config = ConfigDict(from_attributes=True)

    org_id: int


class ReportTemplateAssignmentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_active: Optional[bool] = None
    is_default: Optional[bool] = None
    default_options: Optional[Dict[str, Any]] = None


class ReportTemplateAssignmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    template_id: int
    org_id: int
    entity_type: str
    is_active: bool
    is_default: bool
    default_options: Dict[str, Any] = Field(default_factory=dict)


class ReportPreviewRequest(BaseModel):
    template_id: Optional[int] = None
    template_slug: Optional[str] = None
    # For live editor preview without saving:
    html_content: Optional[str] = None
    css_content: Optional[str] = None
    header_html: Optional[str] = None
    footer_html: Optional[str] = None
    resolver_key: Optional[str] = None
    # Orientation and paper size belong to the page, so a preview rendered
    # without them is always A4 portrait however the editor is set.
    page_size: Optional[str] = Field(None, max_length=20)
    orientation: Optional[str] = Field(None, pattern="^(portrait|landscape)$")
    # "pdf" returns what will actually print, so the editor stops guessing from
    # HTML that no paged renderer ever sees.
    format: Optional[str] = Field("html", pattern="^(html|pdf)$")
    # Bills of Lading and containers are addressed by their business numbers
    # (e.g. "MEDU1234567"), so the identifier may be text as well as an integer.
    # max_length sits on the str member, not the union: on the union Pydantic
    # applies it to integers too and every numeric render fails with a 500.
    entity_id: Optional[Union[int, Annotated[str, Field(min_length=1, max_length=100)]]] = None
    params: Optional[Dict[str, Any]] = None
    _coerce_entity_id = field_validator("entity_id", mode="before")(
        _numeric_entity_ids_stay_integers
    )



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

    id: str
    template_id: int
    entity_type: Optional[str] = None
    entity_id: Optional[int] = None
    status: str
    error_message: Optional[str] = None
    download_url: Optional[str] = None
    requested_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

"""
Schema/ReportDatasetSchema.py
Pydantic schemas for FreightLens Tabular & Dataset Operational Reporting Engine.
Supports parametric multi-record queries, dynamic filtering, multi-level grouping,
subtotals, paper geometry, and multi-format exports (JSON, PDF, Excel).
"""
from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import Optional, List, Dict, Any, Union
from datetime import date, datetime
from decimal import Decimal


class FilterDefinition(BaseModel):
    field: str
    label: str
    type: str  # "date_range", "multi_select", "select", "text", "number_range", "boolean"
    ref_entity: Optional[str] = None  # e.g. "suppliers", "vessels", "unload_venues"
    options: Optional[List[Dict[str, Any]]] = None  # [{"value": "INBOUND", "label": "Inbound"}]
    default_value: Optional[Any] = None
    description: Optional[str] = None


class ColumnDefinition(BaseModel):
    key: str
    label: str
    data_type: str = "string"  # "string", "number", "currency", "date", "badge", "boolean"
    align: str = "left"  # "left", "center", "right"
    width: Optional[str] = None  # e.g. "15%", "120px"
    overflow_mode: Optional[str] = "wrap"  # "wrap" | "truncate"
    format: Optional[str] = None  # e.g. "%Y-%m-%d", "$#,##0.00"
    is_numeric: bool = False
    aggregatable: bool = False  # can be summed in subtotals
    restricted_permission: Optional[str] = None  # e.g. "View_Financials", "View_Supplier"


class DatasetQuerySpec(BaseModel):
    """
    Standardized parameter contract for all tabular and operational reports.
    """
    # Time window filter
    date_field: Optional[str] = None  # e.g., "arrival_date", "order_mail_date", "created_at"
    date_from: Optional[date] = None
    date_to: Optional[date] = None

    # Multi-Entity filters
    supplier_ids: Optional[List[int]] = None
    statuses: Optional[List[str]] = None
    vessel_ids: Optional[List[int]] = None
    venue_ids: Optional[List[int]] = None
    categories: Optional[List[str]] = None
    consignees: Optional[List[str]] = None
    doc_types: Optional[List[str]] = None
    search: Optional[str] = None
    custom_filters: Optional[Dict[str, Any]] = None

    # Sorting & Grouping
    sort_by: Optional[str] = None
    sort_order: Optional[str] = "asc"  # "asc" | "desc"
    group_by: Optional[str] = None  # e.g. "supplier", "status", "vessel", "month"

    # Multi-page & Printing Rules
    break_per_group: Optional[bool] = False  # Start each group on a new page / shift
    repeat_header: Optional[bool] = True
    print_density: Optional[str] = "standard"  # "standard", "compact", "ultra_compact"

    # Paper & Layout Settings
    page_size: Optional[str] = "A4"  # "A4", "A3", "LETTER", "LEGAL", "CUSTOM"
    orientation: Optional[str] = "landscape"  # "landscape", "portrait"
    margin_top: Optional[str] = "12mm"
    margin_bottom: Optional[str] = "12mm"
    margin_left: Optional[str] = "10mm"
    margin_right: Optional[str] = "10mm"
    custom_width_mm: Optional[float] = None
    custom_height_mm: Optional[float] = None

    # Excel Output Settings
    sheet_per_group: Optional[bool] = False  # In Excel export, create one tab per group

    # Pagination for On-Screen Grid View
    page: int = Field(1, ge=1)
    limit: int = Field(50, ge=1, le=1000)

    # Format
    format: Optional[str] = "json"  # "json", "pdf", "xlsx", "csv"

    model_config = ConfigDict(extra="forbid")

    @field_validator("margin_top", "margin_bottom", "margin_left", "margin_right")
    @classmethod
    def validate_css_dimension(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        import re

        if not re.fullmatch(r"\d+(?:\.\d+)?(?:mm|cm|in|pt)", value.strip(), re.IGNORECASE):
            raise ValueError("margin must be a positive CSS length using mm, cm, in, or pt")
        return value.strip().lower()


class DatasetSubtotalGroup(BaseModel):
    group_key: str
    group_label: str
    count: int
    subtotals: Dict[str, Union[float, int, str]] = {}
    records: List[Dict[str, Any]] = []


class DatasetResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    report_key: str
    report_title: str
    category: str
    generated_at: str
    generated_by: str
    org_name: str
    filters_applied: Dict[str, Any] = {}
    columns: List[ColumnDefinition] = []
    
    # Flat records list (always populated)
    records: List[Dict[str, Any]] = []
    total_records: int = 0
    
    # Grouped records (populated if group_by was requested)
    is_grouped: bool = False
    group_field: Optional[str] = None
    groups: List[DatasetSubtotalGroup] = []
    
    # Grand totals & summary metrics
    grand_totals: Dict[str, Union[float, int, str]] = {}
    summary_metrics: Dict[str, Any] = {}

    # Pagination info
    page: int = 1
    pages: int = 1
    limit: int = 50


class DatasetCatalogItem(BaseModel):
    key: str
    name: str
    category: str  # "LOGISTICS", "ORDERS", "INVENTORY"
    description: str
    default_orientation: str = "landscape"
    default_page_size: str = "A4"
    supported_filters: List[FilterDefinition] = []
    supported_sort_fields: List[Dict[str, str]] = []  # [{"key": "arrival_date", "label": "Arrival Date"}]
    supported_group_fields: List[Dict[str, str]] = []  # [{"key": "supplier", "label": "Supplier"}]
    columns: List[ColumnDefinition] = []

"""
Services/report_dataset_service.py
Service layer and resolver registry for FreightLens Dataset and Tabular Operational Reports.
Provides parametric multi-record querying, dynamic filtering, multi-level grouping,
subtotals, permission-aware field redaction, Landscape PDF compilation, and Excel exports.
"""
import logging
from typing import Dict, Any, List, Optional, Callable, Tuple
from datetime import datetime, date
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, func, desc, asc, text, nullslast
from fastapi import HTTPException

from Utils.org_filter import OrgContext, apply_org_filter
from Model import (
    User,
    Organisation,
    ContainerDetails,
    Supplier,
    Vessal,
    BillOfLanding,
    UnloadVenue,
    PurchaseOrder,
    Status,
    ContainerType,
)
from auth.security_guards import is_financial_user, can_view_supplier_user
from Schema.ReportDatasetSchema import (
    DatasetQuerySpec,
    DatasetResult,
    DatasetSubtotalGroup,
    DatasetCatalogItem,
    FilterDefinition,
    ColumnDefinition,
)
from Utils.excel_exporter import build_excel_workbook
from Services.report_render_engine import render_html_document, compile_pdf_from_html

logger = logging.getLogger("containerMgmt.dataset_service")


# ── Dataset Resolver Registration ────────────────────────────────────────────

class DatasetResolverDefinition:
    def __init__(
        self,
        key: str,
        name: str,
        category: str,  # LOGISTICS, ORDERS, INVENTORY
        description: str,
        fn: Callable,
        columns: List[ColumnDefinition],
        filters: List[FilterDefinition],
        sort_fields: List[Dict[str, str]],
        group_fields: List[Dict[str, str]],
        default_orientation: str = "landscape",
        default_page_size: str = "A4",
    ):
        self.key = key
        self.name = name
        self.category = category
        self.description = description
        self.fn = fn
        self.columns = columns
        self.filters = filters
        self.sort_fields = sort_fields
        self.group_fields = group_fields
        self.default_orientation = default_orientation
        self.default_page_size = default_page_size


_DATASET_REGISTRY: Dict[str, DatasetResolverDefinition] = {}


def register_dataset(
    key: str,
    name: str,
    category: str,
    description: str,
    columns: List[ColumnDefinition],
    filters: List[FilterDefinition],
    sort_fields: List[Dict[str, str]],
    group_fields: List[Dict[str, str]],
    default_orientation: str = "landscape",
    default_page_size: str = "A4",
):
    """Decorator to register an operational dataset report resolver."""
    def decorator(fn: Callable):
        _DATASET_REGISTRY[key] = DatasetResolverDefinition(
            key=key,
            name=name,
            category=category,
            description=description,
            fn=fn,
            columns=columns,
            filters=filters,
            sort_fields=sort_fields,
            group_fields=group_fields,
            default_orientation=default_orientation,
            default_page_size=default_page_size,
        )
        return fn
    return decorator


def get_dataset_resolver(key: str) -> DatasetResolverDefinition:
    if key not in _DATASET_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Operational report register '{key}' not found.")
    return _DATASET_REGISTRY[key]


def list_dataset_catalog(user: User, org_context: OrgContext) -> List[DatasetCatalogItem]:
    """Returns the catalog of all available operational dataset registers."""
    can_financial = is_financial_user(user, org_context)
    can_vendor = can_view_supplier_user(user, org_context)

    items = []
    for r in _DATASET_REGISTRY.values():
        # Filter columns based on user permissions
        filtered_cols = []
        for col in r.columns:
            if col.restricted_permission == "View_Financials" and not can_financial:
                continue
            if col.restricted_permission == "View_Supplier" and not can_vendor:
                continue
            filtered_cols.append(col)

        items.append(DatasetCatalogItem(
            key=r.key,
            name=r.name,
            category=r.category,
            description=r.description,
            default_orientation=r.default_orientation,
            default_page_size=r.default_page_size,
            supported_filters=r.filters,
            supported_sort_fields=r.sort_fields,
            supported_group_fields=r.group_fields,
            columns=filtered_cols,
        ))
    return items


# ── General Helper: Grouping & Subtotal Calculation ──────────────────────────

def _group_and_aggregate_records(
    records: List[Dict[str, Any]],
    group_field: str,
    columns: List[ColumnDefinition],
) -> Tuple[List[DatasetSubtotalGroup], Dict[str, Any]]:
    """
    Groups flat records by group_field and calculates subtotal sums and grand totals
    for all aggregatable numeric columns.
    """
    aggregatable_keys = [c.key for c in columns if c.aggregatable or c.is_numeric]
    grouped_map: Dict[str, List[Dict[str, Any]]] = {}
    label_map: Dict[str, str] = {}

    for r in records:
        val = r.get(group_field)
        grp_key = str(val) if val is not None else "Unassigned / Other"
        if grp_key not in grouped_map:
            grouped_map[grp_key] = []
            label_map[grp_key] = str(val or "Unassigned / Other")
        grouped_map[grp_key].append(r)

    groups: List[DatasetSubtotalGroup] = []
    grand_totals: Dict[str, float] = {k: 0.0 for k in aggregatable_keys}

    for grp_key, grp_records in grouped_map.items():
        subtotals: Dict[str, float] = {k: 0.0 for k in aggregatable_keys}
        for item in grp_records:
            for k in aggregatable_keys:
                raw_val = item.get(k)
                if raw_val is not None:
                    try:
                        num = float(raw_val)
                        subtotals[k] += num
                        grand_totals[k] += num
                    except (ValueError, TypeError):
                        pass

        # Round subtotals
        rounded_subtotals = {k: round(v, 2) for k, v in subtotals.items()}
        groups.append(DatasetSubtotalGroup(
            group_key=grp_key,
            group_label=label_map[grp_key],
            count=len(grp_records),
            subtotals=rounded_subtotals,
            records=grp_records,
        ))

    rounded_grand = {k: round(v, 2) for k, v in grand_totals.items()}
    return groups, rounded_grand


# ── Concrete Resolvers ───────────────────────────────────────────────────────

# =============================================================================
# 1. Containers by Vendor / Supplier Register
# =============================================================================

CONTAINERS_BY_VENDOR_COLUMNS = [
    ColumnDefinition(key="container_no", label="Container #", data_type="string", align="left", width="15%"),
    ColumnDefinition(key="container_type", label="Type", data_type="string", align="center", width="8%"),
    ColumnDefinition(key="supplier_name", label="Supplier / Vendor", data_type="string", align="left", width="18%", restricted_permission="View_Supplier"),
    ColumnDefinition(key="bl_number", label="Bill of Lading", data_type="string", align="left", width="14%"),
    ColumnDefinition(key="vessel_name", label="Vessel / Carrier", data_type="string", align="left", width="14%"),
    ColumnDefinition(key="arrival_date", label="Arrival Date", data_type="date", align="center", width="10%"),
    ColumnDefinition(key="status", label="Status", data_type="badge", align="center", width="11%"),
    ColumnDefinition(key="teus", label="TEUs", data_type="number", align="right", width="5%", is_numeric=True, aggregatable=True),
    ColumnDefinition(key="weight", label="Gross Wt (KG)", data_type="number", align="right", width="10%", is_numeric=True, aggregatable=True),
    ColumnDefinition(key="demurrage_days", label="Demurrage Days", data_type="number", align="right", width="8%", is_numeric=True, aggregatable=True),
]

CONTAINERS_BY_VENDOR_FILTERS = [
    FilterDefinition(field="date_range", label="Arrival Date Range", type="date_range"),
    FilterDefinition(field="supplier_ids", label="Suppliers / Vendors", type="multi_select", ref_entity="suppliers"),
    FilterDefinition(
        field="statuses",
        label="Container Status",
        type="multi_select",
        options=[
            {"value": "INBOUND", "label": "Inbound"},
            {"value": "ON_PORT", "label": "On Port"},
            {"value": "IN_TRANSIT", "label": "In Transit"},
            {"value": "COMPLETE", "label": "Complete / Cleared"},
            {"value": "EMPTY", "label": "Empty / Depot"},
        ]
    ),
    FilterDefinition(field="vessel_ids", label="Vessels", type="multi_select", ref_entity="vessels"),
    FilterDefinition(field="venue_ids", label="Unload Venues", type="multi_select", ref_entity="unload_venues"),
    FilterDefinition(field="search", label="Search Container / BL", type="text"),
]

CONTAINERS_SORT_FIELDS = [
    {"key": "arrival_date", "label": "Arrival Date"},
    {"key": "container_no", "label": "Container Number"},
    {"key": "supplier_name", "label": "Supplier Name"},
    {"key": "weight", "label": "Gross Weight"},
    {"key": "demurrage_days", "label": "Demurrage Days"},
]

CONTAINERS_GROUP_FIELDS = [
    {"key": "supplier_name", "label": "By Supplier / Vendor"},
    {"key": "status", "label": "By Status"},
    {"key": "vessel_name", "label": "By Vessel"},
    {"key": "shipping_line", "label": "By Shipping Line"},
    {"key": "arrival_month", "label": "By Arrival Month"},
]


@register_dataset(
    key="containers_by_vendor",
    name="Container Activity by Vendor Register",
    category="LOGISTICS",
    description="Multi-container activity register showing assigned sea containers, carrier routes, TEU counts, and gross weights filtered by vendor, date range, or status.",
    columns=CONTAINERS_BY_VENDOR_COLUMNS,
    filters=CONTAINERS_BY_VENDOR_FILTERS,
    sort_fields=CONTAINERS_SORT_FIELDS,
    group_fields=CONTAINERS_GROUP_FIELDS,
    default_orientation="landscape",
    default_page_size="A4",
)
def resolve_containers_by_vendor(
    spec: DatasetQuerySpec,
    db: Session,
    org_context: OrgContext,
    user: User,
) -> DatasetResult:
    can_vendor = can_view_supplier_user(user, org_context)

    query = db.query(
        ContainerDetails,
        Supplier.name.label("supplier_name"),
        Vessal.VessalNo.label("vessel_name"),
        BillOfLanding.carrier_name.label("bl_shipping_line"),
        BillOfLanding.ArrivalDate.label("bl_arrival_date"),
        Status.name.label("status_name"),
        ContainerType.type.label("type_name"),
    ).outerjoin(
        BillOfLanding, ContainerDetails.BillOfLanding == BillOfLanding.BillOfLanding
    ).outerjoin(
        Supplier, BillOfLanding.Supplier == Supplier.supplier_id
    ).outerjoin(
        Vessal, BillOfLanding.Vessel == Vessal.id
    ).outerjoin(
        Status, ContainerDetails.status == Status.status_id
    ).outerjoin(
        ContainerType, ContainerDetails.type == ContainerType.type_id
    ).filter(
        ContainerDetails.is_deleted == False
    )

    query = apply_org_filter(query, ContainerDetails, org_context)

    # 1. Apply Date Filter
    if spec.date_from:
        query = query.filter(or_(BillOfLanding.ArrivalDate >= spec.date_from, ContainerDetails.unloaded_at_port >= spec.date_from))
    if spec.date_to:
        query = query.filter(or_(BillOfLanding.ArrivalDate <= spec.date_to, ContainerDetails.unloaded_at_port <= spec.date_to))

    # 2. Supplier Filter
    if spec.supplier_ids and len(spec.supplier_ids) > 0:
        query = query.filter(BillOfLanding.Supplier.in_(spec.supplier_ids))

    # 3. Status Filter
    if spec.statuses and len(spec.statuses) > 0:
        query = query.filter(Status.name.in_(spec.statuses))

    # 4. Vessel Filter
    if spec.vessel_ids and len(spec.vessel_ids) > 0:
        query = query.filter(BillOfLanding.Vessel.in_(spec.vessel_ids))

    # 5. Venue Filter
    if spec.venue_ids and len(spec.venue_ids) > 0:
        query = query.filter(ContainerDetails.emptied_at.in_(spec.venue_ids))

    # 6. Text Search
    if spec.search and spec.search.strip():
        term = f"%{spec.search.strip()}%"
        query = query.filter(
            or_(
                ContainerDetails.container_no.ilike(term),
                ContainerDetails.BillOfLanding.ilike(term),
                ContainerDetails.seal_number.ilike(term),
                ContainerDetails.PONo.ilike(term),
            )
        )

    # 7. Sorting
    sort_dir = desc if spec.sort_order == "desc" else asc
    if spec.sort_by == "container_no":
        query = query.order_by(sort_dir(ContainerDetails.container_no))
    elif spec.sort_by == "weight":
        query = query.order_by(sort_dir(ContainerDetails.gross_weight_kg))
    elif spec.sort_by == "supplier_name":
        query = query.order_by(sort_dir(Supplier.name))
    else:
        # Default arrival_date
        query = query.order_by(nullslast(sort_dir(BillOfLanding.ArrivalDate)))

    total_count = query.count()
    rows = query.all()

    # Build Records List
    records = []
    for c, sup_name, ves_name, shp_line, arr_dt, status_name, type_name in rows:
        arr_val = arr_dt or c.unloaded_at_port or c.in_bound
        arr_date = arr_val.strftime("%Y-%m-%d") if arr_val else None
        arr_month = arr_val.strftime("%B %Y") if arr_val else "No Date"
        
        display_supplier = (sup_name or "N/A") if can_vendor else "[REDACTED - VENDOR CONFIDENTIAL]"
        
        c_type = str(type_name or "20GP").upper()
        teu_val = 2.0 if ("40" in c_type or "45" in c_type) else 1.0

        free_days = c.FreeDays or 7
        days_elapsed = 0
        if c.unloaded_at_port:
            end_d = c.empty_date or datetime.utcnow().date()
            days_elapsed = max(0, (end_d - c.unloaded_at_port).days)
        demurrage_days = max(0, days_elapsed - free_days)

        records.append({
            "id": c.Container_ID,
            "container_no": c.container_no,
            "container_type": c_type,
            "supplier_name": display_supplier,
            "bl_number": c.BillOfLanding or "—",
            "vessel_name": ves_name or "—",
            "shipping_line": shp_line or "—",
            "arrival_date": arr_date,
            "arrival_month": arr_month,
            "status": status_name or "ACTIVE",
            "teus": teu_val,
            "weight": float(c.gross_weight_kg or 0.0),
            "demurrage_days": int(demurrage_days),
        })

    # Org branding
    org_rec = db.query(Organisation).filter(Organisation.id == org_context.current_org_id).first()
    org_name = org_rec.name if org_rec else "Sahaj Holding Corp"

    # Filter description map for report header
    filters_applied = {}
    if spec.date_from or spec.date_to:
        filters_applied["arrival_date"] = f"{spec.date_from or 'Start'} to {spec.date_to or 'Present'}"
    if spec.statuses:
        filters_applied["statuses"] = ", ".join(spec.statuses)
    if spec.search:
        filters_applied["search"] = spec.search

    # Grouping calculation
    is_grouped = bool(spec.group_by and spec.group_by != "none")
    groups = []
    grand_totals = {
        "teus": sum(r["teus"] for r in records),
        "weight": round(sum(r["weight"] for r in records), 2),
        "demurrage_days": sum(r["demurrage_days"] for r in records),
    }

    if is_grouped:
        groups, grand_totals = _group_and_aggregate_records(
            records=records,
            group_field=spec.group_by,
            columns=CONTAINERS_BY_VENDOR_COLUMNS,
        )

    return DatasetResult(
        report_key="containers_by_vendor",
        report_title="Container Activity by Vendor Register",
        category="LOGISTICS",
        generated_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        generated_by=getattr(user, "username", "Admin"),
        org_name=org_name,
        filters_applied=filters_applied,
        columns=CONTAINERS_BY_VENDOR_COLUMNS,
        records=records,
        total_records=len(records),
        is_grouped=is_grouped,
        group_field=spec.group_by,
        groups=groups,
        grand_totals=grand_totals,
        summary_metrics={
            "total_containers": len(records),
            "total_teus": grand_totals.get("teus", 0),
            "total_weight_kg": grand_totals.get("weight", 0),
        },
    )


# =============================================================================
# 2. Port Demurrage & Detention Aging Risk Report
# =============================================================================

DEMURRAGE_COLUMNS = [
    ColumnDefinition(key="container_no", label="Container #", data_type="string", align="left", width="15%"),
    ColumnDefinition(key="status", label="Status", data_type="badge", align="center", width="10%"),
    ColumnDefinition(key="supplier_name", label="Supplier", data_type="string", align="left", width="18%", restricted_permission="View_Supplier"),
    ColumnDefinition(key="venue_name", label="Port / Unload Venue", data_type="string", align="left", width="16%"),
    ColumnDefinition(key="arrival_date", label="Arrival Date", data_type="date", align="center", width="11%"),
    ColumnDefinition(key="days_on_port", label="Days on Port", data_type="number", align="right", width="10%", is_numeric=True, aggregatable=True),
    ColumnDefinition(key="demurrage_rate", label="Daily Rate", data_type="currency", align="right", width="10%", is_numeric=True, restricted_permission="View_Financials"),
    ColumnDefinition(key="estimated_demurrage", label="Est. Demurrage", data_type="currency", align="right", width="12%", is_numeric=True, aggregatable=True, restricted_permission="View_Financials"),
]

DEMURRAGE_FILTERS = [
    FilterDefinition(
        field="min_days",
        label="Minimum Days on Port",
        type="select",
        options=[
            {"value": "0", "label": "All Inbound Containers"},
            {"value": "7", "label": "> 7 Days (Approaching Free Time)"},
            {"value": "14", "label": "> 14 Days (Accruing Demurrage)"},
            {"value": "21", "label": "> 21 Days (Critical Detention Risk)"},
        ],
        default_value="7"
    ),
    FilterDefinition(field="venue_ids", label="Unload Venues / Ports", type="multi_select", ref_entity="unload_venues"),
    FilterDefinition(field="supplier_ids", label="Suppliers / Vendors", type="multi_select", ref_entity="suppliers"),
]

DEMURRAGE_SORT_FIELDS = [
    {"key": "estimated_demurrage", "label": "Demurrage Cost (Highest First)"},
    {"key": "days_on_port", "label": "Days on Port"},
    {"key": "arrival_date", "label": "Arrival Date"},
    {"key": "container_no", "label": "Container Number"},
]

DEMURRAGE_GROUP_FIELDS = [
    {"key": "venue_name", "label": "By Port / Unload Venue"},
    {"key": "supplier_name", "label": "By Supplier / Vendor"},
    {"key": "risk_tier", "label": "By Risk Tier (>21d, >14d, >7d)"},
]


@register_dataset(
    key="demurrage_aging_risk",
    name="Port Demurrage & Detention Aging Risk Report",
    category="LOGISTICS",
    description="Identifies containers dwelling at port or terminal past free days, calculates estimated demurrage exposure, and flags critical detention risk tiers.",
    columns=DEMURRAGE_COLUMNS,
    filters=DEMURRAGE_FILTERS,
    sort_fields=DEMURRAGE_SORT_FIELDS,
    group_fields=DEMURRAGE_GROUP_FIELDS,
    default_orientation="landscape",
    default_page_size="A4",
)
def resolve_demurrage_aging_risk(
    spec: DatasetQuerySpec,
    db: Session,
    org_context: OrgContext,
    user: User,
) -> DatasetResult:
    can_financial = is_financial_user(user, org_context)
    can_vendor = can_view_supplier_user(user, org_context)

    query = db.query(
        ContainerDetails,
        Supplier.name.label("supplier_name"),
        UnloadVenue.venue.label("venue_name"),
        BillOfLanding.ArrivalDate.label("bl_arrival_date"),
        Status.name.label("status_name"),
    ).outerjoin(
        BillOfLanding, ContainerDetails.BillOfLanding == BillOfLanding.BillOfLanding
    ).outerjoin(
        Supplier, BillOfLanding.Supplier == Supplier.supplier_id
    ).outerjoin(
        UnloadVenue, ContainerDetails.emptied_at == UnloadVenue.venue_id
    ).outerjoin(
        Status, ContainerDetails.status == Status.status_id
    ).filter(
        ContainerDetails.is_deleted == False
    )

    query = apply_org_filter(query, ContainerDetails, org_context)

    # 1. Minimum days filter
    min_days = 7
    if spec.custom_filters and "min_days" in spec.custom_filters:
        try:
            min_days = int(spec.custom_filters["min_days"])
        except (ValueError, TypeError):
            pass

    if spec.venue_ids:
        query = query.filter(ContainerDetails.emptied_at.in_(spec.venue_ids))
    if spec.supplier_ids:
        query = query.filter(BillOfLanding.Supplier.in_(spec.supplier_ids))

    rows = query.all()
    records = []
    now = datetime.utcnow().date()

    for c, sup_name, ven_name, arr_dt, status_name in rows:
        arr_val = arr_dt or c.unloaded_at_port or c.in_bound
        arr_date = arr_val.date() if isinstance(arr_val, datetime) else arr_val
        days_on_port = (now - arr_date).days if arr_date else 0
        if days_on_port < min_days:
            continue

        # Risk tier classification
        if days_on_port >= 21:
            risk_tier = "CRITICAL (>21 Days)"
        elif days_on_port >= 14:
            risk_tier = "HIGH (>14 Days)"
        else:
            risk_tier = "MODERATE (>7 Days)"

        # Standard estimated daily demurrage rate: $85/day after 7 free days
        free_days = c.FreeDays or 7
        chargeable_days = max(0, days_on_port - free_days)
        daily_rate = 85.0
        est_demurrage = chargeable_days * daily_rate if can_financial else 0.0

        records.append({
            "id": c.Container_ID,
            "container_no": c.container_no,
            "status": status_name or "ON_PORT",
            "supplier_name": (sup_name or "N/A") if can_vendor else "[REDACTED]",
            "venue_name": ven_name or "Main Port Terminal",
            "arrival_date": arr_date.isoformat() if arr_date else None,
            "days_on_port": days_on_port,
            "demurrage_rate": daily_rate if can_financial else None,
            "estimated_demurrage": est_demurrage if can_financial else None,
            "risk_tier": risk_tier,
        })

    # Sort
    reverse = (spec.sort_order != "asc")
    if spec.sort_by == "container_no":
        records.sort(key=lambda r: r["container_no"] or "", reverse=reverse)
    elif spec.sort_by == "days_on_port":
        records.sort(key=lambda r: r["days_on_port"] or 0, reverse=reverse)
    else:
        # Default: estimated_demurrage DESC
        records.sort(key=lambda r: (r["estimated_demurrage"] or 0, r["days_on_port"] or 0), reverse=reverse)

    org_rec = db.query(Organisation).filter(Organisation.id == org_context.current_org_id).first()
    org_name = org_rec.name if org_rec else "Sahaj Holding Corp"

    is_grouped = bool(spec.group_by and spec.group_by != "none")
    groups = []
    grand_totals = {
        "days_on_port": sum(r["days_on_port"] for r in records),
        "estimated_demurrage": round(sum(r["estimated_demurrage"] or 0 for r in records), 2) if can_financial else 0,
    }

    if is_grouped:
        groups, grand_totals = _group_and_aggregate_records(
            records=records,
            group_field=spec.group_by,
            columns=DEMURRAGE_COLUMNS,
        )

    return DatasetResult(
        report_key="demurrage_aging_risk",
        report_title="Port Demurrage & Detention Aging Risk Report",
        category="LOGISTICS",
        generated_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        generated_by=getattr(user, "username", "Admin"),
        org_name=org_name,
        filters_applied={"min_days_threshold": f"> {min_days} Days"},
        columns=DEMURRAGE_COLUMNS,
        records=records,
        total_records=len(records),
        is_grouped=is_grouped,
        group_field=spec.group_by,
        groups=groups,
        grand_totals=grand_totals,
        summary_metrics={
            "overdue_containers_count": len(records),
            "total_estimated_demurrage": grand_totals.get("estimated_demurrage", 0),
        },
    )


# =============================================================================
# 3. Purchase Order Procurement Register
# =============================================================================

PO_REGISTER_COLUMNS = [
    ColumnDefinition(key="po_number", label="PO #", data_type="string", align="left", width="14%"),
    ColumnDefinition(key="po_date", label="Order Date", data_type="date", align="center", width="11%"),
    ColumnDefinition(key="supplier_name", label="Supplier / Vendor", data_type="string", align="left", width="20%", restricted_permission="View_Supplier"),
    ColumnDefinition(key="status", label="Status", data_type="badge", align="center", width="10%"),
    ColumnDefinition(key="lifecycle_stage", label="Pipeline Stage", data_type="string", align="center", width="12%"),
    ColumnDefinition(key="currency", label="Curr", data_type="string", align="center", width="6%"),
    ColumnDefinition(key="total_amount", label="Total Value", data_type="currency", align="right", width="13%", is_numeric=True, aggregatable=True, restricted_permission="View_Financials"),
    ColumnDefinition(key="advance_amount", label="Advance Paid", data_type="currency", align="right", width="13%", is_numeric=True, aggregatable=True, restricted_permission="View_Financials"),
    ColumnDefinition(key="balance_amount", label="Balance Due", data_type="currency", align="right", width="13%", is_numeric=True, aggregatable=True, restricted_permission="View_Financials"),
]

PO_REGISTER_FILTERS = [
    FilterDefinition(field="date_range", label="Order Date Range", type="date_range"),
    FilterDefinition(field="supplier_ids", label="Suppliers / Vendors", type="multi_select", ref_entity="suppliers"),
    FilterDefinition(
        field="lifecycle_stages",
        label="Pipeline Lifecycle Stage",
        type="multi_select",
        options=[
            {"value": "PO_ISSUED", "label": "PO Issued"},
            {"value": "BOOKED", "label": "Vessel Booked"},
            {"value": "SHIPPED", "label": "Shipped (In Transit)"},
            {"value": "PORT_ARRIVAL", "label": "Port Arrival"},
            {"value": "CUSTOMS", "label": "Customs Clearance"},
            {"value": "DELIVERED", "label": "Delivered to Site"},
        ]
    ),
    FilterDefinition(field="search", label="Search PO / Item", type="text"),
]

PO_REGISTER_SORT_FIELDS = [
    {"key": "po_date", "label": "Order Date"},
    {"key": "po_number", "label": "PO Number"},
    {"key": "supplier_name", "label": "Supplier Name"},
    {"key": "total_amount", "label": "Total Amount"},
    {"key": "balance_amount", "label": "Balance Due"},
]

PO_REGISTER_GROUP_FIELDS = [
    {"key": "supplier_name", "label": "By Supplier / Vendor"},
    {"key": "lifecycle_stage", "label": "By Pipeline Stage"},
    {"key": "order_month", "label": "By Order Month"},
    {"key": "currency", "label": "By Currency"},
]


@register_dataset(
    key="po_procurement_register",
    name="Purchase Order Procurement Register",
    category="ORDERS",
    description="Comprehensive procurement log tracking purchase orders, supplier commitments, advance payments, and outstanding balances due.",
    columns=PO_REGISTER_COLUMNS,
    filters=PO_REGISTER_FILTERS,
    sort_fields=PO_REGISTER_SORT_FIELDS,
    group_fields=PO_REGISTER_GROUP_FIELDS,
    default_orientation="landscape",
    default_page_size="A4",
)
def resolve_po_procurement_register(
    spec: DatasetQuerySpec,
    db: Session,
    org_context: OrgContext,
    user: User,
) -> DatasetResult:
    can_financial = is_financial_user(user, org_context)
    can_vendor = can_view_supplier_user(user, org_context)

    query = db.query(
        PurchaseOrder,
        Supplier.name.label("supplier_name"),
    ).outerjoin(
        Supplier, PurchaseOrder.supplier_id == Supplier.supplier_id
    ).filter(
        PurchaseOrder.is_deleted == False
    )

    query = apply_org_filter(query, PurchaseOrder, org_context)

    if spec.date_from:
        query = query.filter(PurchaseOrder.order_mail_date >= spec.date_from)
    if spec.date_to:
        query = query.filter(PurchaseOrder.order_mail_date <= spec.date_to)

    if spec.supplier_ids:
        query = query.filter(PurchaseOrder.supplier_id.in_(spec.supplier_ids))

    if spec.statuses:
        query = query.filter(PurchaseOrder.status.in_(spec.statuses))

    if spec.custom_filters and "lifecycle_stages" in spec.custom_filters:
        stages = spec.custom_filters["lifecycle_stages"]
        if stages:
            query = query.filter(PurchaseOrder.lifecycle_stage.in_(stages))

    if spec.search and spec.search.strip():
        term = f"%{spec.search.strip()}%"
        query = query.filter(
            or_(
                PurchaseOrder.po_number.ilike(term),
                PurchaseOrder.po_nce.ilike(term),
                PurchaseOrder.company.ilike(term),
            )
        )

    # Sorting
    sort_dir = desc if spec.sort_order == "desc" else asc
    if spec.sort_by == "total_amount":
        query = query.order_by(sort_dir(PurchaseOrder.total_amount))
    elif spec.sort_by == "balance_amount":
        query = query.order_by(sort_dir(PurchaseOrder.balance_amount))
    elif spec.sort_by == "po_number":
        query = query.order_by(sort_dir(PurchaseOrder.po_number))
    elif spec.sort_by == "supplier_name":
        query = query.order_by(sort_dir(Supplier.name))
    else:
        query = query.order_by(nullslast(sort_dir(PurchaseOrder.order_mail_date)))

    rows = query.all()
    records = []

    for po, sup_name in rows:
        order_date_str = po.order_mail_date.strftime("%Y-%m-%d") if po.order_mail_date else None
        order_month = po.order_mail_date.strftime("%B %Y") if po.order_mail_date else "No Date"
        
        display_supplier = (sup_name or po.company or "N/A") if can_vendor else "[REDACTED]"
        
        tot_amt = float(po.total_amount or 0.0) if can_financial else None
        adv_amt = float(po.advance_amount or 0.0) if can_financial else None
        bal_amt = float(po.balance_amount or 0.0) if can_financial else None

        records.append({
            "id": po.id,
            "po_number": po.po_number,
            "po_date": order_date_str,
            "order_month": order_month,
            "supplier_name": display_supplier,
            "status": po.status or "DRAFT",
            "lifecycle_stage": po.lifecycle_stage or "PO_ISSUED",
            "currency": po.currency or "USD",
            "total_amount": tot_amt,
            "advance_amount": adv_amt,
            "balance_amount": bal_amt,
        })

    org_rec = db.query(Organisation).filter(Organisation.id == org_context.current_org_id).first()
    org_name = org_rec.name if org_rec else "Sahaj Holding Corp"

    filters_applied = {}
    if spec.date_from or spec.date_to:
        filters_applied["date_range"] = f"{spec.date_from or 'Start'} to {spec.date_to or 'Present'}"

    is_grouped = bool(spec.group_by and spec.group_by != "none")
    groups = []
    grand_totals = {
        "total_amount": round(sum(r["total_amount"] or 0 for r in records), 2) if can_financial else 0,
        "advance_amount": round(sum(r["advance_amount"] or 0 for r in records), 2) if can_financial else 0,
        "balance_amount": round(sum(r["balance_amount"] or 0 for r in records), 2) if can_financial else 0,
    }

    if is_grouped:
        groups, grand_totals = _group_and_aggregate_records(
            records=records,
            group_field=spec.group_by,
            columns=PO_REGISTER_COLUMNS,
        )

    return DatasetResult(
        report_key="po_procurement_register",
        report_title="Purchase Order Procurement Register",
        category="ORDERS",
        generated_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        generated_by=getattr(user, "username", "Admin"),
        org_name=org_name,
        filters_applied=filters_applied,
        columns=PO_REGISTER_COLUMNS,
        records=records,
        total_records=len(records),
        is_grouped=is_grouped,
        group_field=spec.group_by,
        groups=groups,
        grand_totals=grand_totals,
        summary_metrics={
            "total_po_count": len(records),
            "total_commitment_amount": grand_totals.get("total_amount", 0),
            "total_balance_outstanding": grand_totals.get("balance_amount", 0),
        },
    )


# ── Execution Engines: JSON, PDF, Excel ──────────────────────────────────────

def run_dataset_query(
    report_key: str,
    spec: DatasetQuerySpec,
    db: Session,
    org_context: OrgContext,
    user: User,
) -> DatasetResult:
    """Executes query for a report key and returns standard DatasetResult."""
    resolver = get_dataset_resolver(report_key)
    return resolver.fn(spec, db, org_context, user)


def export_dataset_excel(
    report_key: str,
    spec: DatasetQuerySpec,
    db: Session,
    org_context: OrgContext,
    user: User,
) -> bytes:
    """Runs query and serializes into formatted Excel (.xlsx) bytes."""
    dataset = run_dataset_query(report_key, spec, db, org_context, user)
    return build_excel_workbook(dataset, sheet_per_group=bool(spec.sheet_per_group))


def render_dataset_pdf(
    report_key: str,
    spec: DatasetQuerySpec,
    db: Session,
    org_context: OrgContext,
    user: User,
) -> bytes:
    """
    Compiles parameterized dataset into an enterprise landscape PDF using WeasyPrint
    with standardized paper geometry, repeating table headers, and group break rules.
    """
    dataset = run_dataset_query(report_key, spec, db, org_context, user)

    # Declarative Landscape CSS
    css_content = f"""
    @page {{
        size: {spec.page_size or 'A4'} {spec.orientation or 'landscape'};
        margin: {spec.margin_top or '12mm'} {spec.margin_right or '10mm'} {spec.margin_bottom or '12mm'} {spec.margin_left or '10mm'};

        @top-left {{
            content: "{dataset.org_name}";
            font-size: 8pt;
            font-family: 'Inter', sans-serif;
            color: #64748b;
        }}
        @top-center {{
            content: "{dataset.report_title}";
            font-size: 8.5pt;
            font-weight: bold;
            color: #1e293b;
        }}
        @top-right {{
            content: "Generated: {dataset.generated_at}";
            font-size: 8pt;
            color: #64748b;
        }}
        @bottom-left {{
            content: "CLASSIFICATION: INTERNAL OPERATIONAL REGISTER";
            font-size: 7.5pt;
            font-weight: bold;
            color: #94a3b8;
        }}
        @bottom-right {{
            content: "Page " counter(page) " of " counter(pages);
            font-size: 8pt;
            font-weight: bold;
            color: #1e293b;
        }}
    }}

    body {{
        font-family: 'Inter', -apple-system, sans-serif;
        color: #0f172a;
        margin: 0;
        font-size: {'8pt' if spec.print_density == 'compact' else ('7.5pt' if spec.print_density == 'ultra_compact' else '9pt')};
    }}

    .header-box {{
        margin-bottom: 12px;
        padding-bottom: 8px;
        border-bottom: 2px solid #e2e8f0;
    }}
    .report-title {{
        font-size: 14pt;
        font-weight: 800;
        color: #0f172a;
        margin: 0 0 4px 0;
    }}
    .filter-summary {{
        font-size: 8pt;
        color: #64748b;
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 6px;
        padding: 4px 8px;
        margin-top: 4px;
    }}

    table.register-table {{
        width: 100%;
        border-collapse: collapse;
        margin-top: 6px;
    }}
    thead {{
        display: table-header-group;
    }}
    tfoot {{
        display: table-footer-group;
    }}
    tr {{
        page-break-inside: avoid;
    }}
    th {{
        background: #1e293b;
        color: #ffffff;
        font-weight: 600;
        font-size: 8pt;
        padding: {'3px 5px' if spec.print_density == 'ultra_compact' else ('4px 6px' if spec.print_density == 'compact' else '6px 8px')};
        border: 1px solid #334155;
        text-align: left;
    }}
    td {{
        padding: {'3px 5px' if spec.print_density == 'ultra_compact' else ('4px 6px' if spec.print_density == 'compact' else '5px 8px')};
        border: 1px solid #e2e8f0;
        font-size: 8pt;
    }}
    tr:nth-child(even) td {{
        background: #f8fafc;
    }}

    .group-banner {{
        background: #f1f5f9;
        font-weight: bold;
        font-size: 9pt;
        color: #1e293b;
        padding: 6px 8px;
        border-left: 4px solid #3b82f6;
        margin-top: 14px;
        page-break-after: avoid;
        {'page-break-before: always;' if spec.break_per_group else ''}
    }}
    .subtotal-row td {{
        background: #e2e8f0 !important;
        font-weight: bold;
        border-top: 1px solid #94a3b8;
        border-bottom: 2px solid #64748b;
    }}
    .grand-total-row td {{
        background: #cbd5e1 !important;
        font-weight: bold;
        font-size: 9pt;
        border-top: 2px solid #1e293b;
        border-bottom: 3px double #1e293b;
    }}
    """

    # Build HTML Template using Jinja2
    html_template = """
    <div class="header-box">
        <h1 class="report-title">{{ report_title }}</h1>
        <div class="filter-summary">
            <strong>Active Filters:</strong> 
            {% for k, v in filters_applied.items() %}
                {{ k | replace('_', ' ') | title }}: {{ v }}{% if not loop.last %} | {% endif %}
            {% else %}
                All Organization Records
            {% endfor %}
            | <strong>Total Records:</strong> {{ total_records }}
        </div>
    </div>

    {% if is_grouped and groups %}
        {% for grp in groups %}
            <div class="group-banner">
                ▶ {{ grp.group_label }} ({{ grp.count }} records)
            </div>
            <table class="register-table">
                <thead>
                    <tr>
                        {% for col in columns %}
                            <th style="width: {{ col.width }}; text-align: {{ col.align }};">{{ col.label }}</th>
                        {% endfor %}
                    </tr>
                </thead>
                <tbody>
                    {% for row in grp.records %}
                    <tr>
                        {% for col in columns %}
                            <td style="text-align: {{ col.align }};">
                                {% if col.data_type == 'currency' and row[col.key] is not none %}
                                    {{ row[col.key] | format_currency }}
                                {% elif col.data_type == 'number' and row[col.key] is not none %}
                                    {{ row[col.key] | format_number }}
                                {% elif col.data_type == 'date' and row[col.key] is not none %}
                                    {{ row[col.key] }}
                                {% else %}
                                    {{ row[col.key] or '—' }}
                                {% endif %}
                            </td>
                        {% endfor %}
                    </tr>
                    {% endfor %}
                    <tr class="subtotal-row">
                        {% for col in columns %}
                            <td style="text-align: {{ col.align }};">
                                {% if loop.first %}
                                    Subtotal — {{ grp.group_label }}
                                {% elif col.aggregatable and grp.subtotals[col.key] is defined %}
                                    {% if col.data_type == 'currency' %}
                                        {{ grp.subtotals[col.key] | format_currency }}
                                    {% else %}
                                        {{ grp.subtotals[col.key] | format_number }}
                                    {% endif %}
                                {% endif %}
                            </td>
                        {% endfor %}
                    </tr>
                </tbody>
            </table>
        {% endfor %}
    {% else %}
        <table class="register-table">
            <thead>
                <tr>
                    {% for col in columns %}
                        <th style="width: {{ col.width }}; text-align: {{ col.align }};">{{ col.label }}</th>
                    {% endfor %}
                </tr>
            </thead>
            <tbody>
                {% for row in records %}
                <tr>
                    {% for col in columns %}
                        <td style="text-align: {{ col.align }};">
                            {% if col.data_type == 'currency' and row[col.key] is not none %}
                                {{ row[col.key] | format_currency }}
                            {% elif col.data_type == 'number' and row[col.key] is not none %}
                                {{ row[col.key] | format_number }}
                            {% elif col.data_type == 'date' and row[col.key] is not none %}
                                {{ row[col.key] }}
                            {% else %}
                                {{ row[col.key] or '—' }}
                            {% endif %}
                        </td>
                    {% endfor %}
                </tr>
                {% endfor %}
            </tbody>
        </table>
    {% endif %}

    <table class="register-table" style="margin-top: 10px;">
        <tr class="grand-total-row">
            {% for col in columns %}
                <td style="width: {{ col.width }}; text-align: {{ col.align }};">
                    {% if loop.first %}
                        GRAND TOTAL ({{ total_records }} Records)
                    {% elif col.aggregatable and grand_totals[col.key] is defined %}
                        {% if col.data_type == 'currency' %}
                            {{ grand_totals[col.key] | format_currency }}
                        {% else %}
                            {{ grand_totals[col.key] | format_number }}
                        {% endif %}
                    {% endif %}
                </td>
            {% endfor %}
        </tr>
    </table>
    """

    context = dataset.model_dump()
    full_html = render_html_document(
        html_template=html_template,
        context=context,
        css_content=css_content,
        page_size=spec.page_size or "A4",
        orientation=spec.orientation or "landscape",
    )

    return compile_pdf_from_html(full_html)

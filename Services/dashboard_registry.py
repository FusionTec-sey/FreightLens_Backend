"""
Dashboard Planner & Widget Registry Service
Central catalog of dashboard statistics and widgets with module-level permissions,
multi-tenant row isolation (org_id), role templates, and zero-trust data redaction.
"""

from datetime import datetime, timezone
import json
import logging
from typing import Dict, List, Optional, Any
from sqlalchemy import func, text, extract
from sqlalchemy.orm import Session

from Model.containermgmt.Container.ContainerDetails import ContainerDetails
from Model.containermgmt.Container.BillOfLanding import BillOfLanding
from Model.containermgmt.Cinfo.Venue import UnloadVenue
from Model.containermgmt.Orders.Product import Product, ProductCategory
from Model.containermgmt.Orders.PurchaseOrder import PurchaseOrder
from Model.containermgmt.Orders.VendorQuote import VendorQuote
from auth.security_guards import has_permission
from Utils.org_filter import apply_org_filter, OrgContext

logger = logging.getLogger(__name__)

# ==============================================================================
# WIDGET REGISTRY CATALOG
# ==============================================================================

WIDGET_CATALOG = [
    # ── Inventory Module Widgets ───────────────────────────────────────────────
    {
        "id": "inv_total_products",
        "module": "INVENTORY",
        "title": "Active Master SKUs",
        "description": "Total catalogued products active in inventory master.",
        "type": "kpi_stat",
        "required_permission": "View_Product",
        "default_col_span": 1,
        "icon": "Boxes",
        "color": "indigo",
    },
    {
        "id": "inv_low_stock",
        "module": "INVENTORY",
        "title": "Low Stock Alert",
        "description": "Products at or below their minimum reorder stock threshold.",
        "type": "kpi_stat",
        "required_permission": "View_Product",
        "default_col_span": 1,
        "icon": "AlertTriangle",
        "color": "amber",
    },
    {
        "id": "inv_total_valuation",
        "module": "INVENTORY",
        "title": "Total Stock Valuation",
        "description": "Estimated on-hand stock financial value based on primary unit cost.",
        "type": "kpi_stat",
        "required_permission": "Vendor_Pricing_View",  # Zero-trust financial guard
        "default_col_span": 1,
        "icon": "DollarSign",
        "color": "emerald",
    },
    {
        "id": "inv_categories_breakdown",
        "module": "INVENTORY",
        "title": "Inventory Category Distribution",
        "description": "Breakdown of SKUs across primary categories.",
        "type": "donut_chart",
        "required_permission": "View_ProductCategory",
        "default_col_span": 2,
        "icon": "Layers",
        "color": "indigo",
    },

    # ── Logistics & Container Module Widgets ────────────────────────────────────
    {
        "id": "log_active_containers",
        "module": "LOGISTICS",
        "title": "Active Containers",
        "description": "Total active freight containers in circulation.",
        "type": "kpi_stat",
        "required_permission": "View_Container",
        "default_col_span": 1,
        "icon": "Package",
        "color": "blue",
    },
    {
        "id": "log_in_transit",
        "module": "LOGISTICS",
        "title": "In Transit",
        "description": "Containers currently on vessel or in freight transit.",
        "type": "kpi_stat",
        "required_permission": "View_Container",
        "default_col_span": 1,
        "icon": "Truck",
        "color": "yellow",
    },
    {
        "id": "log_on_port",
        "module": "LOGISTICS",
        "title": "On Port / Terminal",
        "description": "Containers arrived at destination port awaiting gate pass or clearance.",
        "type": "kpi_stat",
        "required_permission": "View_Container",
        "default_col_span": 1,
        "icon": "Anchor",
        "color": "blue",
    },
    {
        "id": "log_gate_pass",
        "module": "LOGISTICS",
        "title": "Gate Pass Issued",
        "description": "Containers cleared from port and en route to warehouse.",
        "type": "kpi_stat",
        "required_permission": "View_Container",
        "default_col_span": 1,
        "icon": "BadgeCheck",
        "color": "purple",
    },
    {
        "id": "log_demurrage_alerts",
        "module": "LOGISTICS",
        "title": "Demurrage / D&D Alerts",
        "description": "Containers exceeding free days or at risk of demurrage / detention penalties.",
        "type": "kpi_stat",
        "required_permission": "View_Container",
        "default_col_span": 1,
        "icon": "AlertTriangle",
        "color": "rose",
    },
    {
        "id": "log_bills_of_lading",
        "module": "LOGISTICS",
        "title": "Bills of Lading (B/L)",
        "description": "Active ocean freight manifests, shipping lines, and carrier shipments.",
        "type": "kpi_stat",
        "required_permission": "View_Container",
        "default_col_span": 1,
        "icon": "FileText",
        "color": "blue",
    },
    {
        "id": "log_completed_containers",
        "module": "LOGISTICS",
        "title": "Completed Containers",
        "description": "Historical archive of returned, discharged, and completed containers.",
        "type": "kpi_stat",
        "required_permission": "View_Container",
        "default_col_span": 1,
        "icon": "CheckCircle",
        "color": "emerald",
    },
    {
        "id": "log_monthly_trend",
        "module": "LOGISTICS",
        "title": "Monthly Container Trend",
        "description": "12-month container volume trend for destination ports.",
        "type": "bar_chart",
        "required_permission": "View_Container",
        "default_col_span": 2,
        "icon": "BarChart2",
        "color": "blue",
    },
    {
        "id": "wh_recent_arrivals",
        "module": "WAREHOUSE",
        "title": "Recent Container Arrivals",
        "description": "List of recently arrived containers and delivery venues.",
        "type": "table",
        "required_permission": "View_Container",
        "default_col_span": 4,
        "icon": "CheckCircle",
        "color": "emerald",
    },

    # ── Procurement & Orders Module Widgets ─────────────────────────────────────
    {
        "id": "po_active_orders",
        "module": "ORDERS",
        "title": "Open Purchase Orders",
        "description": "Active purchase orders in production, packing, or shipping.",
        "type": "kpi_stat",
        "required_permission": "View_Order",
        "default_col_span": 1,
        "icon": "ShoppingCart",
        "color": "indigo",
    },
    {
        "id": "po_pending_approval",
        "module": "ORDERS",
        "title": "POs Pending Approval",
        "description": "Purchase orders in draft or submitted stage awaiting approval.",
        "type": "kpi_stat",
        "required_permission": "View_Order",
        "default_col_span": 1,
        "icon": "FileText",
        "color": "amber",
    },
    {
        "id": "po_rfqs_active",
        "module": "ORDERS",
        "title": "Active RFQ Comparisons",
        "description": "Sourcing quote requests open for supplier bidding.",
        "type": "kpi_stat",
        "required_permission": "View_RFQ",
        "default_col_span": 1,
        "icon": "TrendingUp",
        "color": "purple",
    },
    {
        "id": "po_spend_overview",
        "module": "ORDERS",
        "title": "Procurement Spend (YTD)",
        "description": "Cumulative purchase order commitment for the current fiscal year.",
        "type": "kpi_stat",
        "required_permission": "Vendor_Pricing_View",  # Zero-trust financial guard
        "default_col_span": 1,
        "icon": "DollarSign",
        "color": "emerald",
    },
]

# Map widget ID to metadata
WIDGET_MAP = {w["id"]: w for w in WIDGET_CATALOG}

# ==============================================================================
# DEFAULT ROLE TEMPLATES
# ==============================================================================

ROLE_DEFAULT_TEMPLATES = {
    "Administrator": {
        "name": "Executive & Operations Master",
        "description": "Complete cross-module overview covering Inventory, Logistics, and Procurement.",
        "widgets": [
            {"id": "inv_total_products", "col_span": 1, "visible": True},
            {"id": "inv_low_stock", "col_span": 1, "visible": True},
            {"id": "log_active_containers", "col_span": 1, "visible": True},
            {"id": "po_active_orders", "col_span": 1, "visible": True},
            {"id": "log_monthly_trend", "col_span": 2, "visible": True},
            {"id": "inv_categories_breakdown", "col_span": 2, "visible": True},
            {"id": "wh_recent_arrivals", "col_span": 4, "visible": True},
        ]
    },
    "Inventory_Manager": {
        "name": "Inventory & Warehouse Lead",
        "description": "Focused on SKU health, reorder levels, category valuation, and incoming shipments.",
        "widgets": [
            {"id": "inv_total_products", "col_span": 1, "visible": True},
            {"id": "inv_low_stock", "col_span": 1, "visible": True},
            {"id": "inv_total_valuation", "col_span": 1, "visible": True},
            {"id": "log_active_containers", "col_span": 1, "visible": True},
            {"id": "inv_categories_breakdown", "col_span": 4, "visible": True},
            {"id": "wh_recent_arrivals", "col_span": 4, "visible": True},
        ]
    },
    "Logistics_Operator": {
        "name": "Logistics & Fleet Coordinator",
        "description": "Focused on sea-freight containers, port clearances, transit stages, and deliveries.",
        "widgets": [
            {"id": "log_active_containers", "col_span": 1, "visible": True},
            {"id": "log_in_transit", "col_span": 1, "visible": True},
            {"id": "log_on_port", "col_span": 1, "visible": True},
            {"id": "log_gate_pass", "col_span": 1, "visible": True},
            {"id": "log_demurrage_alerts", "col_span": 1, "visible": True},
            {"id": "log_bills_of_lading", "col_span": 1, "visible": True},
            {"id": "log_completed_containers", "col_span": 1, "visible": True},
            {"id": "log_monthly_trend", "col_span": 2, "visible": True},
            {"id": "wh_recent_arrivals", "col_span": 4, "visible": True},
        ]
    },
    "Procurement_Officer": {
        "name": "Procurement & Sourcing Lead",
        "description": "Focused on purchase orders, vendor RFQs, pipeline progress, and shipments.",
        "widgets": [
            {"id": "po_active_orders", "col_span": 1, "visible": True},
            {"id": "po_pending_approval", "col_span": 1, "visible": True},
            {"id": "po_rfqs_active", "col_span": 1, "visible": True},
            {"id": "inv_low_stock", "col_span": 1, "visible": True},
            {"id": "log_active_containers", "col_span": 1, "visible": True},
            {"id": "log_in_transit", "col_span": 1, "visible": True},
            {"id": "wh_recent_arrivals", "col_span": 4, "visible": True},
        ]
    },
    "Standard_User": {
        "name": "Standard Operational Layout",
        "description": "Default view with core inventory and container stats.",
        "widgets": [
            {"id": "inv_total_products", "col_span": 1, "visible": True},
            {"id": "log_active_containers", "col_span": 1, "visible": True},
            {"id": "log_in_transit", "col_span": 1, "visible": True},
            {"id": "wh_recent_arrivals", "col_span": 4, "visible": True},
        ]
    }
}

# ==============================================================================
# PERMISSION & CATALOG FILTERING
# ==============================================================================

def get_authorized_widgets(current_user) -> List[Dict[str, Any]]:
    """Return all widgets from catalog that the current user has permission to view."""
    authorized = []
    for w in WIDGET_CATALOG:
        perm = w.get("required_permission")
        if not perm or has_permission(current_user, perm):
            authorized.append(w)
    return authorized


def filter_layout_for_user(layout_widgets: List[Dict[str, Any]], current_user) -> List[Dict[str, Any]]:
    """Clean a widget layout to keep only widgets existing in catalog and permitted for user."""
    auth_ids = {w["id"] for w in get_authorized_widgets(current_user)}
    cleaned = []
    seen = set()
    for item in layout_widgets:
        wid = item.get("id")
        if wid in auth_ids and wid not in seen:
            seen.add(wid)
            meta = WIDGET_MAP.get(wid, {})
            cleaned.append({
                "id": wid,
                "col_span": item.get("col_span", meta.get("default_col_span", 1)),
                "visible": item.get("visible", True),
                "title": meta.get("title", wid),
                "module": meta.get("module", "GENERAL"),
                "type": meta.get("type", "kpi_stat"),
                "icon": meta.get("icon", "Boxes"),
                "color": meta.get("color", "indigo"),
            })
    return cleaned


# ==============================================================================
# DATABASE LAYOUT OPERATIONS
# ==============================================================================

def get_user_layout(db: Session, current_user, org_context: OrgContext) -> Dict[str, Any]:
    """
    Fetch user's saved dashboard layout from usercredentials.user_dashboard_configs.
    Falls back to role-matching template or system default.
    """
    is_postgres = (db.bind.dialect.name == "postgresql")
    user_schema = "usercredentials." if is_postgres else ""
    org_id = org_context.org_id

    # 1. Check user custom layout
    try:
        row = db.execute(text(f"""
            SELECT id, widgets, layout_mode, template_id 
            FROM {user_schema}user_dashboard_configs
            WHERE user_id = :user_id AND org_id = :org_id AND is_deleted = FALSE
            ORDER BY updated_at DESC LIMIT 1
        """), {"user_id": current_user.id, "org_id": org_id}).fetchone()

        if row and row[1]:
            raw_widgets = row[1]
            if isinstance(raw_widgets, str):
                raw_widgets = json.loads(raw_widgets)
            cleaned = filter_layout_for_user(raw_widgets, current_user)
            if cleaned:
                return {
                    "source": "user_custom",
                    "layout_mode": row[2] or "grid",
                    "template_id": row[3],
                    "widgets": cleaned
                }
    except Exception as e:
        logger.error(f"Error fetching user dashboard config: {e}")

    # 2. Check role default template in containermgmt.dashboard_templates
    user_roles = [r.name for r in getattr(current_user, "roles", [])]
    if not user_roles:
        user_roles = ["Standard_User"]
    biz_schema = "containermgmt." if is_postgres else ""

    try:
        t_row = db.execute(text(f"""
            SELECT id, name, widgets 
            FROM {biz_schema}dashboard_templates
            WHERE org_id = :org_id AND role_name = ANY(:user_roles) AND is_deleted = FALSE
            ORDER BY is_default DESC, updated_at DESC LIMIT 1
        """), {"org_id": org_id, "user_roles": user_roles}).fetchone()

        if t_row and t_row[2]:
            raw_widgets = t_row[2]
            if isinstance(raw_widgets, str):
                raw_widgets = json.loads(raw_widgets)
            cleaned = filter_layout_for_user(raw_widgets, current_user)
            if cleaned:
                return {
                    "source": "role_template_db",
                    "template_id": t_row[0],
                    "template_name": t_row[1],
                    "layout_mode": "grid",
                    "widgets": cleaned
                }
    except Exception as e:
        logger.error(f"Error fetching role template from db: {e}")

    # 3. Fallback to hardcoded role template or Standard_User
    tpl = None
    for r in user_roles:
        if r in ROLE_DEFAULT_TEMPLATES:
            tpl = ROLE_DEFAULT_TEMPLATES[r]
            break
    if not tpl:
        tpl = ROLE_DEFAULT_TEMPLATES["Standard_User"]

    cleaned = filter_layout_for_user(tpl["widgets"], current_user)
    return {
        "source": "preset_template",
        "template_name": tpl["name"],
        "layout_mode": "grid",
        "widgets": cleaned
    }


def save_user_layout(db: Session, current_user, org_context: OrgContext, widgets: List[Dict[str, Any]], layout_mode: str = "grid", template_id: Optional[int] = None) -> Dict[str, Any]:
    """Persist user custom dashboard layout in user_dashboard_configs."""
    is_postgres = (db.bind.dialect.name == "postgresql")
    user_schema = "usercredentials." if is_postgres else ""
    org_id = org_context.org_id

    # Filter widgets to only valid permitted ones
    cleaned = filter_layout_for_user(widgets, current_user)
    widgets_json = json.dumps([{"id": w["id"], "col_span": w.get("col_span", 1), "visible": w.get("visible", True)} for w in cleaned])
    now = datetime.now(timezone.utc)

    # Upsert or update existing config
    existing_id = db.execute(text(f"""
        SELECT id FROM {user_schema}user_dashboard_configs
        WHERE user_id = :user_id AND org_id = :org_id AND is_deleted = FALSE
    """), {"user_id": current_user.id, "org_id": org_id}).scalar()

    if existing_id:
        db.execute(text(f"""
            UPDATE {user_schema}user_dashboard_configs
            SET widgets = CAST(:widgets AS jsonb), layout_mode = :layout_mode, template_id = :template_id,
                updated_by = :user_id, updated_at = :updated_at
            WHERE id = :id
        """), {
            "id": existing_id,
            "widgets": widgets_json,
            "layout_mode": layout_mode,
            "template_id": template_id,
            "user_id": current_user.id,
            "updated_at": now
        })
    else:
        db.execute(text(f"""
            INSERT INTO {user_schema}user_dashboard_configs
            (user_id, org_id, template_id, widgets, layout_mode, created_by, updated_by, created_at, updated_at)
            VALUES (:user_id, :org_id, :template_id, CAST(:widgets AS jsonb), :layout_mode, :user_id, :user_id, :now, :now)
        """), {
            "user_id": current_user.id,
            "org_id": org_id,
            "template_id": template_id,
            "widgets": widgets_json,
            "layout_mode": layout_mode,
            "now": now
        })

    db.commit()
    return {"success": True, "widgets_count": len(cleaned)}


def reset_user_layout(db: Session, current_user, org_context: OrgContext) -> Dict[str, Any]:
    """Delete user custom layout so it resets to role default."""
    is_postgres = (db.bind.dialect.name == "postgresql")
    user_schema = "usercredentials." if is_postgres else ""
    org_id = org_context.org_id

    db.execute(text(f"""
        UPDATE {user_schema}user_dashboard_configs
        SET is_deleted = TRUE, deleted_at = :now, deleted_by = :user_id
        WHERE user_id = :user_id AND org_id = :org_id AND is_deleted = FALSE
    """), {"user_id": current_user.id, "org_id": org_id, "now": datetime.now(timezone.utc)})
    db.commit()

    return get_user_layout(db, current_user, org_context)


# ==============================================================================
# LIVE DATA CALCULATION (ORG-ISOLATED & PERMISSION-CHECKED)
# ==============================================================================

def calculate_dashboard_data(db: Session, current_user, org_context: OrgContext, year: Optional[int] = None) -> Dict[str, Any]:
    """
    Computes all live KPI metrics and chart datasets for widgets that current user
    is authorized to access, with multi-tenant row isolation.
    """
    data = {}
    current_year = year or datetime.now().year

    # 1. Inventory Metrics (guarded by View_Product)
    if has_permission(current_user, "View_Product"):
        try:
            p_query = db.query(Product).filter(Product.is_deleted == False)
            p_query = apply_org_filter(p_query, Product, org_context)

            total_skus = p_query.count()
            low_stock_count = p_query.filter(
                Product.current_stock <= Product.min_stock_quantity,
                Product.min_stock_quantity > 0
            ).count()

            data["inv_total_products"] = {"value": total_skus, "unit": "SKUs"}
            data["inv_low_stock"] = {"value": low_stock_count, "unit": "SKUs", "alert": low_stock_count > 0}

            # Inventory Valuation (zero-trust check on Vendor_Pricing_View)
            if has_permission(current_user, "Vendor_Pricing_View"):
                try:
                    val_result = db.query(
                        func.sum(Product.current_stock * func.coalesce(Product.unit_cost, 0))
                    ).filter(Product.is_deleted == False)
                    val_result = apply_org_filter(val_result, Product, org_context).scalar()

                    data["inv_total_valuation"] = {
                        "value": round(float(val_result or 0), 2),
                        "formatted": f"${(val_result or 0):,.2f}",
                        "unit": "USD"
                    }
                except Exception as e:
                    logger.warning(f"Failed to calculate inventory valuation: {e}")
        except Exception as e:
            logger.warning(f"Failed to calculate inventory metrics: {e}")

    # 2. Inventory Category Breakdown (guarded by View_ProductCategory)
    if has_permission(current_user, "View_ProductCategory"):
        try:
            cat_counts = (
                db.query(ProductCategory.name, func.count(Product.id))
                .outerjoin(Product, (Product.category_id == ProductCategory.id) & (Product.is_deleted == False))
                .filter(ProductCategory.is_deleted == False)
            )
            cat_counts = apply_org_filter(cat_counts, ProductCategory, org_context)
            rows = cat_counts.group_by(ProductCategory.name).order_by(func.count(Product.id).desc()).limit(7).all()

            data["inv_categories_breakdown"] = {
                "labels": [r[0] for r in rows],
                "series": [r[1] for r in rows],
            }
        except Exception as e:
            logger.warning(f"Failed to calculate category breakdown: {e}")

    # 3. Logistics & Container Metrics (guarded by View_Container)
    if has_permission(current_user, "View_Container") or has_permission(current_user, "View_Containers"):
        c_query = db.query(ContainerDetails).filter(ContainerDetails.is_deleted == False)
        c_query = apply_org_filter(c_query, ContainerDetails, org_context)

        try:
            total_active_c = c_query.filter(ContainerDetails.status != 4).count()
            in_transit_c = c_query.filter(ContainerDetails.status == 1).count()
            on_port_c = c_query.filter(ContainerDetails.status == 2).count()
            gate_pass_c = c_query.filter(ContainerDetails.status == 3).count()
            completed_c = c_query.filter(ContainerDetails.status == 4).count()
            arrived_c = c_query.filter(ContainerDetails.status == 6).count()
            emptied_c = c_query.filter(ContainerDetails.status == 7).count()

            data["log_active_containers"] = {"value": total_active_c, "unit": "Containers"}
            data["log_in_transit"] = {"value": in_transit_c, "unit": "Containers"}
            data["log_on_port"] = {"value": on_port_c, "unit": "Containers"}
            data["log_gate_pass"] = {"value": gate_pass_c, "unit": "Containers"}
            data["log_completed_containers"] = {"value": completed_c, "unit": "Containers"}

            # Demurrage & Detention alerts (active containers where arrival date + free days has lapsed)
            try:
                # Active containers on port or arrived that have arrived and exceeded free days
                demurrage_q = (
                    db.query(ContainerDetails.Container_ID)
                    .join(BillOfLanding, BillOfLanding.BillOfLanding == ContainerDetails.BillOfLanding)
                    .filter(
                        ContainerDetails.is_deleted == False,
                        ContainerDetails.status.notin_([1, 4]),  # Exclude in-transit and completed
                        BillOfLanding.ArrivalDate.isnot(None),
                        text("CURRENT_DATE - CAST(\"BillOfLanding\".\"ArrivalDate\" AS DATE) > COALESCE(\"ContainerDetails\".\"free_days\", \"BillOfLanding\".\"free_days\", 14)")
                    )
                )
                demurrage_q = apply_org_filter(demurrage_q, ContainerDetails, org_context)
                demurrage_count = demurrage_q.count()
            except Exception as d_err:
                logger.warning(f"Failed SQL demurrage calculation, fallback: {d_err}")
                demurrage_count = 0

            data["log_demurrage_alerts"] = {
                "value": demurrage_count,
                "unit": "Containers",
                "alert": demurrage_count > 0
            }

            # Bills of Lading Count
            try:
                bl_query = db.query(BillOfLanding).filter(BillOfLanding.is_deleted == False)
                bl_query = apply_org_filter(bl_query, BillOfLanding, org_context)
                data["log_bills_of_lading"] = {"value": bl_query.count(), "unit": "Manifests"}
            except Exception as bl_err:
                logger.warning(f"Failed to calculate bills of lading count: {bl_err}")
                data["log_bills_of_lading"] = {"value": 0, "unit": "Manifests"}

        except Exception as e:
            logger.warning(f"Failed to calculate container counts: {e}")

        # Monthly Container Trends (12 months by Arrival Date)
        months_arr = [0] * 12
        try:
            m_query = (
                db.query(
                    extract('month', BillOfLanding.ArrivalDate).label('month'),
                    func.count(ContainerDetails.Container_ID).label('count')
                )
                .outerjoin(BillOfLanding, BillOfLanding.BillOfLanding == ContainerDetails.BillOfLanding)
                .filter(
                    ContainerDetails.is_deleted == False,
                    extract('year', BillOfLanding.ArrivalDate) == current_year
                )
            )
            m_query = apply_org_filter(m_query, ContainerDetails, org_context)
            m_rows = (
                m_query
                .group_by(extract('month', BillOfLanding.ArrivalDate))
                .order_by(extract('month', BillOfLanding.ArrivalDate))
                .all()
            )
            for month_num, count in m_rows:
                if month_num is not None and 1 <= int(month_num) <= 12:
                    months_arr[int(month_num) - 1] = count
        except Exception as e:
            logger.warning(f"Failed to aggregate monthly container trend: {e}")

        data["log_monthly_trend"] = {
            "year": current_year,
            "total": sum(months_arr),
            "months": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
            "series": months_arr
        }

        # Recent container arrivals
        try:
            arrivals = (
                c_query.filter(ContainerDetails.status == 6)
                .outerjoin(UnloadVenue, ContainerDetails.emptied_at == UnloadVenue.venue_id)
                .with_entities(
                    ContainerDetails.container_no,
                    ContainerDetails.seal_number,
                    ContainerDetails.in_bound,
                    UnloadVenue.venue
                )
                .order_by(ContainerDetails.updated_at.desc())
                .limit(10)
                .all()
            )
            data["wh_recent_arrivals"] = [
                {
                    "container_no": r[0],
                    "seal_no": r[1] or "—",
                    "eta": r[2].isoformat() if r[2] else "—",
                    "location": r[3] or "Warehouse Bay"
                }
                for r in arrivals
            ]
        except Exception as e:
            logger.warning(f"Failed to aggregate recent container arrivals: {e}")
            data["wh_recent_arrivals"] = []

    # 4. Procurement & Orders Metrics (guarded by View_Order)
    if has_permission(current_user, "View_Order"):
        try:
            po_query = db.query(PurchaseOrder).filter(PurchaseOrder.is_deleted == False)
            po_query = apply_org_filter(po_query, PurchaseOrder, org_context)

            active_pos = po_query.filter(PurchaseOrder.status.notin_(["completed", "cancelled", "draft"])).count()
            pending_pos = po_query.filter(PurchaseOrder.status.in_(["draft", "submitted", "pending_approval"])).count()

            data["po_active_orders"] = {"value": active_pos, "unit": "Orders"}
            data["po_pending_approval"] = {"value": pending_pos, "unit": "Orders", "alert": pending_pos > 0}

            # Spend YTD (zero-trust check on Vendor_Pricing_View)
            if has_permission(current_user, "Vendor_Pricing_View"):
                try:
                    spend_result = db.query(
                        func.sum(PurchaseOrder.total_amount)
                    ).filter(
                        PurchaseOrder.is_deleted == False,
                        PurchaseOrder.status != "cancelled",
                        extract('year', func.coalesce(PurchaseOrder.order_mail_date, PurchaseOrder.created_at)) == current_year
                    )
                    spend_result = apply_org_filter(spend_result, PurchaseOrder, org_context).scalar()
                    data["po_spend_overview"] = {
                        "value": round(float(spend_result or 0), 2),
                        "formatted": f"${(spend_result or 0):,.2f}",
                        "unit": "USD",
                        "year": current_year
                    }
                except Exception as e:
                    logger.warning(f"Failed to aggregate PO spend: {e}")
        except Exception as e:
            logger.warning(f"Failed to aggregate PO metrics: {e}")

    # 5. RFQ Active Quotes (guarded by View_RFQ)
    if has_permission(current_user, "View_RFQ"):
        try:
            vq_query = db.query(VendorQuote).filter(VendorQuote.is_deleted == False, func.upper(VendorQuote.status) == "PENDING")
            vq_query = apply_org_filter(vq_query, VendorQuote, org_context)
            rfq_count = vq_query.count()
            data["po_rfqs_active"] = {"value": rfq_count, "unit": "RFQs"}
        except Exception as e:
            logger.warning(f"Failed to count active RFQs: {e}")

    return data

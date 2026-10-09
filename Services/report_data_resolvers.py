"""
Services/report_data_resolvers.py
Data Resolver Registry and Built-in Resolvers for the Report & Print Template System.
Resolvers query the database with multi-tenant row isolation and permission-aware field redaction.
"""
import logging
import base64
from typing import Dict, Any, Optional, Callable, List
from datetime import datetime, date
from decimal import Decimal
from fastapi import HTTPException
from sqlalchemy.orm import Session

from Utils.org_filter import OrgContext, apply_org_filter
from Model.Credentials.users import User
from Model.Credentials.Organisation import Organisation
from Model.containermgmt.Report.OrgPrintProfile import OrgPrintProfile
from auth.security_guards import is_financial_user, can_view_supplier_user
from Services.report_time_service import org_today_iso

logger = logging.getLogger("containerMgmt.report_resolvers")


class ResolverDefinition:
    def __init__(
        self,
        key: str,
        name: str,
        category: str,
        entity_type: str,
        description: str,
        fn: Callable,
        schema_meta: Dict[str, Any],
        sample_context: Dict[str, Any],
        print_permissions: List[str],
    ):
        self.key = key
        self.name = name
        self.category = category
        self.entity_type = entity_type
        self.description = description
        self.fn = fn
        self.schema_meta = schema_meta
        self.sample_context = sample_context
        self.print_permissions = tuple(print_permissions)


_RESOLVER_REGISTRY: Dict[str, ResolverDefinition] = {}


def register_resolver(
    key: str,
    name: str,
    category: str,
    entity_type: str,
    description: str,
    schema_meta: Dict[str, Any],
    sample_context: Dict[str, Any],
    print_permissions: List[str],
):
    """Decorator to register a data resolver function in the registry."""
    def decorator(fn: Callable):
        _RESOLVER_REGISTRY[key] = ResolverDefinition(
            key=key,
            name=name,
            category=category,
            entity_type=entity_type,
            description=description,
            fn=fn,
            schema_meta=schema_meta,
            sample_context=sample_context,
            print_permissions=print_permissions,
        )
        return fn
    return decorator


def get_resolver(key: str) -> ResolverDefinition:
    if key not in _RESOLVER_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Report data resolver '{key}' not found.")
    return _RESOLVER_REGISTRY[key]


def list_resolvers(category: Optional[str] = None) -> List[Dict[str, Any]]:
    results = []
    for r in _RESOLVER_REGISTRY.values():
        if category and r.category.upper() != category.upper():
            continue
        results.append({
            "resolver_key": r.key,
            "name": r.name,
            "category": r.category,
            "entity_type": r.entity_type,
            "description": r.description,
            "fields": r.schema_meta,
        })
    return results


def _clean_val(v: Any) -> Any:
    """Helper to convert dates and Decimals to JSON/template-friendly formats."""
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    return v


def _asset_data_uri(key: Optional[str]) -> Optional[str]:
    if not key:
        return None
    try:
        from Utils.blob_storage import blob_storage

        body, content_type, _ = blob_storage.get_file(key)
        if body is None:
            return None
        content = body.read()
        return f"data:{content_type};base64,{base64.b64encode(content).decode('ascii')}"
    except Exception:
        logger.warning("Unable to resolve report asset %s", key, exc_info=True)
        return None


def _resolve_company_profile(db: Session, org_id: Optional[int]) -> Dict[str, Any]:
    """Resolve tenant-owned print identity without leaking another organisation's data."""
    organisation = None
    profile = None
    if org_id:
        organisation = db.query(Organisation).filter(Organisation.id == org_id).first()
        profile = db.query(OrgPrintProfile).filter(
            OrgPrintProfile.org_id == org_id,
            OrgPrintProfile.is_deleted.is_(False),
        ).first()

    name = (
        getattr(profile, "legal_name", None)
        or getattr(organisation, "display_name", None)
        or getattr(organisation, "name", None)
        or "Organisation"
    )
    logo_key = getattr(profile, "logo_asset_key", None)
    stamp_key = getattr(profile, "stamp_asset_key", None)
    signature_key = getattr(profile, "signature_asset_key", None)
    return {
        "name": name,
        "legal_name": getattr(profile, "legal_name", None) or name,
        "address": getattr(profile, "address", None),
        "tax_id": getattr(profile, "tax_id", None),
        "phone": getattr(profile, "contact_phone", None),
        "email": getattr(profile, "contact_email", None),
        "logo_asset_key": logo_key,
        "stamp_asset_key": stamp_key,
        "signature_asset_key": signature_key,
        "logo_data_uri": _asset_data_uri(logo_key),
        "stamp_data_uri": _asset_data_uri(stamp_key),
        "signature_data_uri": _asset_data_uri(signature_key),
        "bank_details": dict(getattr(profile, "bank_details", None) or {}),
        "default_terms": dict(getattr(profile, "default_terms", None) or {}),
        "brand_color": getattr(profile, "brand_color", None) or "#1E40AF",
        "font_family": getattr(profile, "font_family", None) or "Arial",
        "locale": getattr(profile, "locale", None) or "en-SC",
        "timezone": getattr(profile, "timezone", None) or "Indian/Mahe",
    }


# ─────────────────────────────────────────────────────────────────────────────
# 1. Purchase Order Resolver
# ─────────────────────────────────────────────────────────────────────────────

PO_SCHEMA_META = {
    "po_number": {"type": "string", "description": "Purchase order number", "example": "PO-2026-0042"},
    "po_nce": {"type": "string", "description": "Internal Accounts reference / NPO", "example": "NPO-8821"},
    "doc_type": {"type": "string", "description": "Document classification (PO or RFQ)", "example": "PO"},
    "status": {"type": "string", "description": "Order status code", "example": "ORDERED"},
    "status_label": {"type": "string", "description": "Human readable status", "example": "Ordered"},
    "lifecycle_stage": {"type": "string", "description": "Procurement pipeline stage", "example": "PO_ISSUED"},
    "order_mail_date": {"type": "string", "description": "Order creation / issue date", "example": "2026-03-15"},
    "eta_date": {"type": "string", "description": "Expected delivery date", "example": "2026-04-10"},
    "currency": {"type": "string", "description": "Currency code", "example": "USD"},
    "consignee": {"type": "string", "description": "Consignee destination name", "example": "Noble Construction Ltd"},
    "freight_type": {"type": "string", "description": "Freight transport mode", "example": "Sea Freight"},
    "remark": {"type": "string", "description": "General notes and remarks", "example": "Urgent site delivery required."},
    "show_financials": {"type": "boolean", "description": "True if user is authorized to view financials"},
    "show_vendor": {"type": "boolean", "description": "True if user is authorized to view supplier identities"},
    "supplier": {
        "type": "object",
        "restricted": True,
        "permission": "View_Supplier",
        "description": "Supplier contact information (redacted if unauthorized)",
        "item_fields": {
            "name": {"type": "string", "example": "Global Steel Industries Ltd"},
            "code": {"type": "string", "example": "SUP-104"},
            "contact_person": {"type": "string", "example": "Mr. Rajiv Shah"},
            "email": {"type": "string", "example": "orders@globalsteel.com"},
            "phone": {"type": "string", "example": "+91 98200 12345"},
            "address": {"type": "string", "example": "Sector 4, Industrial Area, Gujarat, India"},
        },
    },
    "company": {
        "type": "object",
        "description": "Issuing company / organization details",
        "item_fields": {
            "name": {"type": "string", "example": "Sahaj Holding Corp"},
            "address": {"type": "string", "example": "Victoria Commercial Center, Mahe, Seychelles"},
            "tax_id": {"type": "string", "example": "TAX-SEY-99201"},
            "phone": {"type": "string", "example": "+248 4 123 456"},
            "email": {"type": "string", "example": "procurement@sahaj.sc"},
        },
    },
    "items": {
        "type": "array",
        "description": "Line items on the purchase order",
        "item_fields": {
            "item_code": {"type": "string", "example": "STL-REBAR-16MM"},
            "description": {"type": "string", "example": "High Tensile TMT Rebar 16mm x 12m"},
            "quantity_ordered": {"type": "number", "example": 500.0},
            "unit": {"type": "string", "example": "MT"},
            "unit_price": {"type": "number", "restricted": True, "permission": "View_Financials", "example": 680.00},
            "total_price": {"type": "number", "restricted": True, "permission": "View_Financials", "example": 340000.00},
            "notes": {"type": "string", "example": "Grade Fe 500D with mill test certificate."},
        },
    },
    "subtotal": {"type": "number", "restricted": True, "permission": "View_Financials", "example": 340000.00},
    "advance_amount": {"type": "number", "restricted": True, "permission": "View_Financials", "example": 68000.00},
    "balance_amount": {"type": "number", "restricted": True, "permission": "View_Financials", "example": 272000.00},
    "total_amount": {"type": "number", "restricted": True, "permission": "View_Financials", "example": 340000.00},
}

PO_SAMPLE_CONTEXT = {
    "po_number": "PO-2026-0042",
    "po_date": "2026-03-15",
    "po_nce": "NPO-8821",
    "doc_type": "PO",
    "status": "ORDERED",
    "status_label": "Ordered",
    "lifecycle_stage": "PO_ISSUED",
    "order_mail_date": "2026-03-15",
    "report_date": "2026-03-26",
    "generated_by": "Administrator",
    "org_name": "Sahaj Holding Corp",
    "eta_date": "2026-04-10",
    "currency": "USD",
    "consignee": "Noble Construction Ltd",
    "consignee_name": "Noble Construction Ltd",
    "freight_type": "Sea Freight",
    "remark": "Urgent site delivery required. Deliver to Central Yard.",
    "show_financials": True,
    "show_vendor": True,
    "supplier_name": "Global Steel Industries Ltd",
    "supplier_address": "Sector 4, Industrial Area, Gujarat, India",
    "supplier_email": "orders@globalsteel.com",
    "company": {
        "name": "Sahaj Holding Corp",
        "address": "Victoria Commercial Center, Mahe, Seychelles",
        "tax_id": "TAX-SEY-99201",
        "phone": "+248 4 123 456",
        "email": "procurement@sahaj.sc",
    },
    "supplier": {
        "name": "Global Steel Industries Ltd",
        "code": "SUP-104",
        "contact_person": "Mr. Rajiv Shah",
        "email": "orders@globalsteel.com",
        "phone": "+91 98200 12345",
        "address": "Sector 4, Industrial Area, Gujarat, India",
    },
    "items": [
        {
            "sku": "STL-REBAR-16MM",
            "item_code": "STL-REBAR-16MM",
            "description": "High Tensile TMT Rebar 16mm x 12m (Grade Fe 500D)",
            "quantity": 250.0,
            "quantity_ordered": 250.0,
            "unit": "MT",
            "unit_price": 680.00,
            "total_price": 170000.00,
            "notes": "Mill test certs required prior to vessel dispatch.",
        },
        {
            "sku": "STL-WIRE-4MM",
            "item_code": "STL-WIRE-4MM",
            "description": "GI Binding Wire 4mm coils",
            "quantity": 15.0,
            "quantity_ordered": 15.0,
            "unit": "TONS",
            "unit_price": 720.00,
            "total_price": 10800.00,
            "notes": "Standard waterproof bundle wrap.",
        },
    ],
    "subtotal": 180800.00,
    "advance_amount": 54240.00,
    "balance_amount": 126560.00,
    "total_amount": 180800.00,
}


@register_resolver(
    key="purchase_order",
    name="Purchase Order",
    category="ORDERS",
    entity_type="PurchaseOrder",
    description="Resolves Purchase Order or RFQ headers, line items, supplier contacts, and financial summaries.",
    schema_meta=PO_SCHEMA_META,
    sample_context=PO_SAMPLE_CONTEXT,
    print_permissions=["Print_PurchaseOrder", "View_Order"],
)
def resolve_purchase_order(
    entity_id: int,
    db: Session,
    org_context: OrgContext,
    user: User,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    from Model.containermgmt.Orders.PurchaseOrder import PurchaseOrder
    from Model.containermgmt.Orders.POItem import POItem

    query = db.query(PurchaseOrder).filter(
        PurchaseOrder.id == entity_id,
        PurchaseOrder.is_deleted == False,
    )
    po = apply_org_filter(query, PurchaseOrder, org_context).first()

    if not po:
        raise HTTPException(status_code=404, detail=f"Purchase order with ID {entity_id} not found or access denied.")

    # Permissions
    can_financial = is_financial_user(user, org_context)
    can_vendor = can_view_supplier_user(user, org_context)
    is_rfq = (getattr(po, "doc_type", "PO") or "PO").upper() == "RFQ"

    # RFQs never show final financials even to financial users
    allow_financials = can_financial and (not is_rfq)

    company_data = _resolve_company_profile(db, po.org_id)

    # Supplier info
    supplier_data = {}
    if can_vendor and po.supplier_rel:
        sup = po.supplier_rel
        supplier_data = {
            "name": getattr(sup, "company_name", None) or getattr(sup, "supplier_name", None) or po.company,
            "code": getattr(sup, "supplier_code", None),
            "contact_person": getattr(sup, "contact_person", None),
            "email": getattr(sup, "email", None),
            "phone": getattr(sup, "phone", None),
            "address": getattr(sup, "address", None),
        }
    elif can_vendor:
        supplier_data = {
            "name": po.company,
            "code": None,
            "contact_person": None,
            "email": None,
            "phone": None,
            "address": None,
        }
    else:
        supplier_data = {
            "name": "[REDACTED - VENDOR CONFIDENTIAL]",
            "code": None,
            "contact_person": None,
            "email": None,
            "phone": None,
            "address": None,
        }

    # Items
    items_list = []
    calculated_subtotal = Decimal("0.00")
    for item in po.items:
        if getattr(item, "is_deleted", False):
            continue
        item_qty = Decimal(str(item.quantity_ordered or 0))
        item_dict = {
            "sku": item.item_code,
            "item_code": item.item_code,
            "description": item.description,
            "quantity": float(item_qty),
            "quantity_ordered": float(item_qty),
            "unit": item.unit or "PCS",
            "notes": item.notes,
        }
        if allow_financials:
            unit_price = Decimal(str(item.unit_price or 0))
            line_total = Decimal(str(item.total_price or (item_qty * unit_price)))
            calculated_subtotal += line_total
            item_dict["unit_price"] = float(unit_price)
            item_dict["total_price"] = float(line_total)
        else:
            item_dict["unit_price"] = None
            item_dict["total_price"] = None
        items_list.append(item_dict)

    # Financial totals
    subtotal = float(calculated_subtotal) if allow_financials else None
    advance = float(po.advance_amount) if (allow_financials and po.advance_amount is not None) else None
    balance = float(po.balance_amount) if (allow_financials and po.balance_amount is not None) else None
    total = float(po.total_amount) if (allow_financials and po.total_amount is not None) else subtotal

    return {
        "po_number": po.po_number,
        "po_date": _clean_val(po.order_mail_date),
        "po_nce": po.po_nce,
        "doc_type": po.doc_type or "PO",
        "status": po.status,
        "status_label": po.status_label or po.status,
        "lifecycle_stage": po.lifecycle_stage,
        "order_mail_date": _clean_val(po.order_mail_date),
        "eta_date": _clean_val(po.eta_date),
        "currency": po.currency or "USD",
        "consignee": po.consignee,
        "consignee_name": po.consignee,
        "freight_type": po.freight_type or "Sea Freight",
        "remark": po.remark,
        "show_financials": allow_financials,
        "show_vendor": can_vendor,
        "company": company_data,
        "org_name": company_data.get("name"),
        "supplier": supplier_data,
        "supplier_name": supplier_data.get("name"),
        "supplier_address": supplier_data.get("address"),
        "supplier_email": supplier_data.get("email"),
        "report_date": org_today_iso(db, org_context),
        "generated_by": getattr(user, "username", "System"),
        "items": items_list,
        "subtotal": subtotal,
        "advance_amount": advance,
        "balance_amount": balance,
        "total_amount": total,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 2. Defect Report Resolver
# ─────────────────────────────────────────────────────────────────────────────

DEFECT_SCHEMA_META = {
    "defect_number": {"type": "string", "description": "Defect report unique ID", "example": "DEF-2026-0001"},
    "report_type": {"type": "string", "description": "GOODS_DEFECT or CONTAINER_DAMAGE", "example": "GOODS_DEFECT"},
    "category": {"type": "string", "description": "Shortage, Damaged, Quality Issue, etc.", "example": "Damaged"},
    "status": {"type": "string", "description": "OPEN, UNDER_REVIEW, RESOLVED, CLOSED", "example": "OPEN"},
    "title": {"type": "string", "description": "Defect headline / summary", "example": "Cracked Ceramic Tiles in Container"},
    "description": {"type": "string", "description": "Detailed explanation of defect", "example": "Pallet 3 fell over causing tile breakage."},
    "discovery_date": {"type": "string", "description": "Date defect was identified", "example": "2026-03-20"},
    "unloading_date": {"type": "string", "description": "Date container was unloaded", "example": "2026-03-19"},
    "resolution_type": {"type": "string", "description": "REPLACEMENT, CREDIT_NOTE, REFUND, etc.", "example": "CREDIT_NOTE"},
    "resolution_notes": {"type": "string", "description": "Resolution specifics", "example": "Supplier agreed to issue credit note for damaged boxes."},
    "resolved_at": {"type": "string", "description": "Date resolution finalized", "example": "2026-03-24"},
    "po_number": {"type": "string", "description": "Related PO number if linked", "example": "PO-2026-0042"},
    "container_no": {"type": "string", "description": "Related container number", "example": "MSKU9021884"},
    "bill_of_lading_no": {"type": "string", "description": "Related B/L number", "example": "MEDU992144"},
    "items": {
        "type": "array",
        "description": "List of affected items",
        "item_fields": {
            "item_description": {"type": "string", "example": "Vitrified Porcelain Floor Tiles 60x60cm"},
            "quantity_affected": {"type": "number", "example": 45.0},
            "unit": {"type": "string", "example": "BOXES"},
            "notes": {"type": "string", "example": "Shattered upon container opening."},
        },
    },
    "images": {
        "type": "array",
        "description": "Photographic evidence attached to defect report",
        "item_fields": {
            "image_url": {"type": "string", "example": "/api/blob/view?key=defects/1/photo1.jpg"},
            "caption": {"type": "string", "example": "Broken tile boxes near rear door."},
        },
    },
}

DEFECT_SAMPLE_CONTEXT = {
    "defect_number": "DEF-2026-0001",
    "report_type": "GOODS_DEFECT",
    "category": "Damaged",
    "status": "OPEN",
    "title": "Cracked Ceramic Tiles in Container MSKU9021884",
    "description": "Upon opening the container, Pallet 3 was found tilted and multiple carton boxes had crushed corners.",
    "discovery_date": "2026-03-20",
    "unloading_date": "2026-03-19",
    "resolution_type": "CREDIT_NOTE",
    "resolution_notes": "Supplier notified via claim email. Credit note pending verification.",
    "resolved_at": None,
    "po_number": "PO-2026-0042",
    "container_no": "MSKU9021884",
    "bill_of_lading_no": "MEDU992144",
    "items": [
        {
            "item_description": "Vitrified Porcelain Floor Tiles 60x60cm (Beige)",
            "quantity_affected": 42.0,
            "unit": "BOXES",
            "notes": "Tiles broken inside crushed cartons.",
        },
        {
            "item_description": "Tile Grout 5kg Pack (Ivory)",
            "quantity_affected": 5.0,
            "unit": "BAGS",
            "notes": "Punctured packaging with powder leakage.",
        },
    ],
    "images": [
        {
            "image_url": "https://dummyimage.com/600x400/e2e8f0/475569.png&text=Defect+Photo+1",
            "caption": "Pallet 3 collapse inside container.",
        }
    ],
}


@register_resolver(
    key="defect_report",
    name="Defect & Damage Report",
    category="ORDERS",
    entity_type="DefectReport",
    description="Resolves material defects, damage inspections, affected quantities, photos, and claim resolutions.",
    schema_meta=DEFECT_SCHEMA_META,
    sample_context=DEFECT_SAMPLE_CONTEXT,
    print_permissions=["View_Defect"],
)
def resolve_defect_report(
    entity_id: int,
    db: Session,
    org_context: OrgContext,
    user: User,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    from Model.containermgmt.Orders.DefectReport import DefectReport

    query = db.query(DefectReport).filter(
        DefectReport.id == entity_id,
        DefectReport.is_deleted == False,
    )
    defect = apply_org_filter(query, DefectReport, org_context).first()

    if not defect:
        raise HTTPException(status_code=404, detail=f"Defect report with ID {entity_id} not found or access denied.")

    items_list = []
    for item in defect.items:
        items_list.append({
            "item_description": item.item_description,
            "quantity_affected": float(item.quantity_affected or 0),
            "unit": item.unit or "PCS",
            "notes": item.notes,
        })

    images_list = []
    for img in defect.images:
        images_list.append({
            "image_url": getattr(img, "image_url", None) or getattr(img, "file_path", None),
            "caption": getattr(img, "caption", None) or getattr(img, "description", None),
        })

    po_num = defect.purchase_order.po_number if defect.purchase_order else None
    cntr_no = defect.container.Container_No if defect.container else None

    return {
        "defect_number": defect.defect_number,
        "report_type": defect.report_type,
        "category": defect.category,
        "status": defect.status,
        "title": defect.title,
        "description": defect.description,
        "discovery_date": _clean_val(defect.discovery_date),
        "unloading_date": _clean_val(defect.unloading_date),
        "resolution_type": defect.resolution_type,
        "resolution_notes": defect.resolution_notes,
        "resolved_at": _clean_val(defect.resolved_at),
        "po_number": po_num,
        "container_no": cntr_no,
        "bill_of_lading_no": defect.bill_of_lading_no,
        "items": items_list,
        "images": images_list,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 3. Bill of Lading Summary Resolver
# ─────────────────────────────────────────────────────────────────────────────

BL_SCHEMA_META = {
    "bl_number": {"type": "string", "description": "Master Bill of Lading number", "example": "MEDU992144"},
    "carrier_name": {"type": "string", "description": "Ocean freight carrier name", "example": "MSC Mediterranean Shipping"},
    "vessel_name": {"type": "string", "description": "Carrying vessel name", "example": "MSC ELISA"},
    "voyage_number": {"type": "string", "description": "Voyage identifier", "example": "2402E"},
    "origin_port": {"type": "string", "description": "Port of Loading (POL)", "example": "Nhava Sheva, India"},
    "destination_port": {"type": "string", "description": "Port of Discharge (POD)", "example": "Port Victoria, Seychelles"},
    "shipped_on_board_date": {"type": "string", "description": "Date vessel departed origin", "example": "2026-03-02"},
    "arrival_date": {"type": "string", "description": "ETA or Actual Discharge Date", "example": "2026-03-22"},
    "free_days": {"type": "number", "description": "Agreed demurrage free days at port", "example": 14},
    "consignee_name": {"type": "string", "description": "Consignee organization", "example": "Noble Construction Ltd"},
    "supplier_name": {"type": "string", "restricted": True, "permission": "View_Supplier", "description": "Shipper / Supplier name", "example": "Global Steel Industries Ltd"},
    "total_containers": {"type": "number", "description": "Count of linked containers", "example": 3},
    "containers": {
        "type": "array",
        "description": "Containers on this Bill of Lading",
        "item_fields": {
            "container_no": {"type": "string", "example": "MSKU9021884"},
            "container_type": {"type": "string", "example": "40HC"},
            "seal_no": {"type": "string", "example": "SL-991204"},
            "weight": {"type": "number", "example": 26500.0},
            "status": {"type": "string", "example": "At Port"},
            "location": {"type": "string", "example": "Victoria Port Yard 2"},
            "demurrage_days": {"type": "number", "example": 2},
        },
    },
}

BL_SAMPLE_CONTEXT = {
    "bl_number": "MEDU992144",
    "carrier_name": "MSC Mediterranean Shipping Company",
    "vessel_name": "MSC ELISA",
    "voyage_number": "2402E",
    "origin_port": "Nhava Sheva (INNSA), India",
    "destination_port": "Port Victoria (SCPOV), Seychelles",
    "shipped_on_board_date": "2026-03-02",
    "arrival_date": "2026-03-22",
    "free_days": 14,
    "consignee_name": "Noble Construction Ltd",
    "supplier_name": "Global Steel Industries Ltd",
    "total_containers": 2,
    "containers": [
        {
            "container_no": "MSKU9021884",
            "container_type": "40HC",
            "seal_no": "SL-991204",
            "weight": 26500.0,
            "status": "Customs Cleared",
            "location": "Port Victoria Yard 2",
            "demurrage_days": 0,
        },
        {
            "container_no": "MSKU7712390",
            "container_type": "20GP",
            "seal_no": "SL-991205",
            "weight": 18200.0,
            "status": "In Transit to Yard",
            "location": "Providence Industrial Zone",
            "demurrage_days": 0,
        },
    ],
}


@register_resolver(
    key="bl_summary",
    name="Bill of Lading Summary",
    category="LOGISTICS",
    entity_type="BillOfLanding",
    description="Resolves ocean manifest, port-to-port voyage dates, carrier details, and container manifests.",
    schema_meta=BL_SCHEMA_META,
    sample_context=BL_SAMPLE_CONTEXT,
    print_permissions=["Print_BillOfLanding", "View_BL"],
)
def resolve_bl_summary(
    entity_id: Any,
    db: Session,
    org_context: OrgContext,
    user: User,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    from Model.containermgmt.Container.BillOfLanding import BillOfLanding
    from Model.containermgmt.Container.ContainerDetails import ContainerDetails

    # entity_id might be string BL number or int ID
    query = db.query(BillOfLanding).filter(
        (BillOfLanding.BillOfLanding == str(entity_id)) | (getattr(BillOfLanding, "id", None) == entity_id),
        BillOfLanding.is_deleted == False,
    )
    bl = apply_org_filter(query, BillOfLanding, org_context).first()

    if not bl:
        raise HTTPException(status_code=404, detail=f"Bill of Lading '{entity_id}' not found or access denied.")

    can_vendor = can_view_supplier_user(user, org_context)

    # Carrier & vessel
    carrier = bl.carrier_name or (bl.provider_rel.LogisticsProvider if bl.provider_rel else None)
    vessel = bl.vessel_rel.VessalName if bl.vessel_rel else None
    consignee = bl.consignee_rel.Consignee if bl.consignee_rel else None
    supplier = "[REDACTED]"
    if can_vendor:
        supplier = bl.supplier_rel.Supplier if bl.supplier_rel else None

    # Containers
    containers_list = []
    for c in bl.containers:
        if getattr(c, "is_deleted", False):
            continue
        containers_list.append({
            "container_no": c.Container_No,
            "container_type": getattr(c, "container_type", None) or "40HC",
            "seal_no": getattr(c, "seal_no", None),
            "weight": float(c.Weight) if c.Weight is not None else None,
            "status": c.status_rel.Status if c.status_rel else None,
            "location": c.location_rel.Location if c.location_rel else None,
            "demurrage_days": getattr(c, "demurrage_days", 0),
        })

    return {
        "bl_number": bl.BillOfLanding,
        "carrier_name": carrier,
        "vessel_name": vessel,
        "voyage_number": None,
        "origin_port": bl.origin_port,
        "destination_port": bl.destination_port,
        "shipped_on_board_date": _clean_val(bl.shipped_on_board_date),
        "arrival_date": _clean_val(bl.ArrivalDate),
        "free_days": bl.FreeDays,
        "consignee_name": consignee,
        "supplier_name": supplier,
        "total_containers": len(containers_list),
        "containers": containers_list,
    }


# -------------------------------------------------------------------------
# Container Operational Details & Demurrage Slip
# -------------------------------------------------------------------------

CONTAINER_SCHEMA_META = {
    "container_no": {"type": "string", "example": "MSKU9021884"},
    "container_type": {"type": "string", "example": "40HC"},
    "status_name": {"type": "string", "example": "On Port"},
    "bl_number": {"type": "string", "example": "MEDU992144"},
    "vessel_name": {"type": "string", "example": "MSC AGATHA"},
    "carrier_name": {"type": "string", "example": "Mediterranean Shipping Company"},
    "arrival_date": {"type": "string", "example": "2026-03-22"},
    "in_bound_date": {"type": "string", "example": "2026-03-24"},
    "empty_date": {"type": "string", "example": "2026-03-28"},
    "unloaded_at_port": {"type": "string", "example": "2026-03-23"},
    "emptied_at": {"type": "string", "example": "Providence Depot"},
    "free_days": {"type": "number", "example": 14},
    "seal_number": {"type": "string", "example": "SL-991205"},
    "gross_weight_kg": {"type": "number", "example": 24500.0},
    "gross_volume_cbm": {"type": "number", "example": 68.5},
    "note": {"type": "string", "example": "Cleared customs with priority green channel."},
    "po_number": {"type": "string", "example": "PO-2026-0042"},
    "materials": {
        "type": "array",
        "description": "Materials assigned to this container",
        "item_fields": {
            "name": {"type": "string", "example": "Ceramic Tiles 60x60"},
        },
    },
    "consignee_name": {"type": "string", "example": "Sahajanand Enterprises Pty Ltd"},
    "supplier_name": {"type": "string", "example": "Global Ceramics India"},
}

CONTAINER_SAMPLE_CONTEXT = {
    "container_no": "MSKU9021884",
    "container_type": "40HC",
    "status_name": "On Port",
    "bl_number": "MEDU992144",
    "vessel_name": "MSC AGATHA",
    "carrier_name": "Mediterranean Shipping Company",
    "arrival_date": "2026-03-22",
    "in_bound_date": "2026-03-24",
    "empty_date": None,
    "unloaded_at_port": "2026-03-23",
    "emptied_at": "Providence Yard",
    "free_days": 14,
    "seal_number": "SL-991205",
    "gross_weight_kg": 24500.0,
    "gross_volume_cbm": 68.5,
    "note": "Container cleared customs and is ready for yard de-stuffing.",
    "po_number": "PO-2026-0042",
    "materials": [
        {"name": "Vitrified Porcelain Floor Tiles 60x60cm"},
        {"name": "Waterproof Tile Adhesive 25kg bags"},
    ],
    "consignee_name": "Sahajanand Enterprises Pty Ltd",
    "supplier_name": "Global Ceramics India",
}


@register_resolver(
    key="container_details",
    name="Container Operational Notice",
    category="LOGISTICS",
    entity_type="ContainerDetails",
    description="Resolves container tracking status, associated bill of lading, vessel, arrival date, free days, and cargo details.",
    schema_meta=CONTAINER_SCHEMA_META,
    sample_context=CONTAINER_SAMPLE_CONTEXT,
    print_permissions=["Print_Container", "View_Container"],
)
def resolve_container_details(
    entity_id: Any,
    db: Session,
    org_context: OrgContext,
    user: User,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    from Model.containermgmt.Container.ContainerDetails import ContainerDetails

    query = db.query(ContainerDetails).filter(ContainerDetails.is_deleted == False)
    if str(entity_id).isdigit():
        query = query.filter((ContainerDetails.Container_ID == int(entity_id)) | (ContainerDetails.container_no == str(entity_id)))
    else:
        query = query.filter(ContainerDetails.container_no == str(entity_id))

    container = apply_org_filter(query, ContainerDetails, org_context).first()
    if not container:
        raise HTTPException(status_code=404, detail=f"Container '{entity_id}' not found or access denied.")

    bl = container.bill_of_landing
    status_name = "In Transit"
    if container.status_rel:
        status_name = getattr(container.status_rel, "Status", None) or getattr(container.status_rel, "name", None) or "In Transit"

    type_name = "40HC"
    if container.type_rel:
        type_name = getattr(container.type_rel, "type", None) or getattr(container.type_rel, "name", None) or "40HC"

    venue_name = None
    if container.emptied_at_rel:
        venue_name = getattr(container.emptied_at_rel, "venue", None) or getattr(container.emptied_at_rel, "name", None)

    mat_list = []
    if hasattr(container, "materials") and container.materials:
        for m in container.materials:
            m_name = getattr(m, "Material", None) or getattr(m, "material_name", None) or str(m)
            mat_list.append({"name": m_name})

    can_vendor = can_view_supplier_user(user, org_context)
    supplier = "[REDACTED]"
    if can_vendor and bl and bl.supplier_rel:
        supplier = bl.supplier_rel.Supplier

    consignee = None
    if bl and bl.consignee_rel:
        consignee = bl.consignee_rel.Consignee

    return {
        "container_no": container.container_no,
        "container_type": type_name,
        "status_name": status_name,
        "bl_number": container.BillOfLanding or (bl.BillOfLanding if bl else None),
        "vessel_name": bl.vessel_rel.VessalName if (bl and bl.vessel_rel) else None,
        "carrier_name": bl.carrier_name if bl else None,
        "arrival_date": _clean_val(bl.ArrivalDate) if bl else None,
        "in_bound_date": _clean_val(container.in_bound),
        "empty_date": _clean_val(container.empty_date),
        "unloaded_at_port": _clean_val(container.unloaded_at_port),
        "emptied_at": venue_name,
        "free_days": container.FreeDays or (bl.FreeDays if bl else 14),
        "seal_number": container.seal_number,
        "gross_weight_kg": float(container.gross_weight_kg) if container.gross_weight_kg is not None else None,
        "gross_volume_cbm": float(container.gross_volume_cbm) if container.gross_volume_cbm is not None else None,
        "note": container.note,
        "po_number": container.PONo,
        "materials": mat_list,
        "consignee_name": consignee,
        "supplier_name": supplier,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 4. Sourcing & Requisition RFQ Resolver
# ─────────────────────────────────────────────────────────────────────────────

RFQ_SCHEMA_META = {
    "rfq_number": {"type": "string", "description": "RFQ / Requisition reference number", "example": "RFQ-2026-0089"},
    "po_nce": {"type": "string", "description": "Internal procurement requisition code", "example": "REQ-4011"},
    "doc_type": {"type": "string", "description": "Document type", "example": "RFQ"},
    "status": {"type": "string", "description": "Procurement status code", "example": "SOURCING"},
    "status_label": {"type": "string", "description": "Status label", "example": "Sourcing / RFQ Open"},
    "lifecycle_stage": {"type": "string", "description": "Requisition stage", "example": "SOURCING"},
    "issue_date": {"type": "string", "description": "RFQ issuance date", "example": "2026-03-20"},
    "due_date": {"type": "string", "description": "Quotation submission deadline", "example": "2026-04-05"},
    "currency": {"type": "string", "description": "Requested quote currency", "example": "USD"},
    "consignee": {"type": "string", "description": "Consignee destination name", "example": "Noble Construction Ltd"},
    "consignee_name": {"type": "string", "description": "Consignee destination name", "example": "Noble Construction Ltd"},
    "destination_port": {"type": "string", "description": "Delivery destination port or site", "example": "Port Victoria, Seychelles"},
    "freight_type": {"type": "string", "description": "Requested shipping mode", "example": "Sea Freight"},
    "remark": {"type": "string", "description": "Scope notes and special bidding conditions", "example": "Technical datasheets and test certificates required with quote submission."},
    "buyer_contact": {"type": "string", "description": "Direct email for quote submission", "example": "procurement@sahaj.sc"},
    "show_budget": {"type": "boolean", "description": "Whether estimated budget amounts are visible (internal use only)"},
    "company": {
        "type": "object",
        "description": "Issuing company / organization details",
        "item_fields": {
            "name": {"type": "string", "example": "Sahaj Holding Corp"},
            "address": {"type": "string", "example": "Victoria Commercial Center, Mahe, Seychelles"},
            "tax_id": {"type": "string", "example": "TAX-SEY-99201"},
            "phone": {"type": "string", "example": "+248 4 123 456"},
            "email": {"type": "string", "example": "procurement@sahaj.sc"},
        },
    },
    "supplier": {
        "type": "object",
        "description": "Targeted supplier details if issued to a specific vendor",
        "item_fields": {
            "name": {"type": "string", "example": "Prospective Bidder / Supplier"},
            "code": {"type": "string", "example": "BID-01"},
            "contact_person": {"type": "string", "example": "Sales Department"},
            "email": {"type": "string", "example": "sales@supplier.com"},
        },
    },
    "items": {
        "type": "array",
        "description": "Line items requested for quotation",
        "item_fields": {
            "line_no": {"type": "number", "example": 1},
            "item_code": {"type": "string", "example": "STL-BEAM-HEA200"},
            "description": {"type": "string", "example": "Structural Steel HEA 200 Beams (S275JR) 12m length"},
            "quantity_requested": {"type": "number", "example": 45.0},
            "unit": {"type": "string", "example": "MT"},
            "technical_specifications": {"type": "string", "example": "Grade S275JR with EN 10204 3.1 mill test certificates."},
            "notes": {"type": "string", "example": "Mill test certs required with shipment."},
            "estimated_unit_price": {"type": "number", "restricted": True, "permission": "View_Financials", "example": 850.00},
            "estimated_total": {"type": "number", "restricted": True, "permission": "View_Financials", "example": 38250.00},
        },
    },
    "total_items": {"type": "number", "example": 5},
    "instructions": {
        "type": "array",
        "description": "Standard terms and quotation submission guidelines",
        "example": [
            "Please submit itemized unit and total pricing including freight terms (CIF Port Victoria preferred).",
            "Indicate manufacturer origin, warranty duration, and lead time in calendar days.",
            "All quotations must remain valid for a minimum of 30 days from the closing date.",
        ],
    },
}

RFQ_SAMPLE_CONTEXT = {
    "rfq_number": "RFQ-2026-0089",
    "po_number": "RFQ-2026-0089",
    "po_nce": "REQ-4011",
    "doc_type": "RFQ",
    "status": "SOURCING",
    "status_label": "Sourcing / RFQ Open",
    "lifecycle_stage": "SOURCING",
    "issue_date": "2026-03-20",
    "rfq_date": "2026-03-20",
    "due_date": "2026-04-05",
    "eta_date": "2026-04-05",
    "report_date": "2026-03-28",
    "currency": "USD",
    "consignee": "Noble Construction Ltd",
    "consignee_name": "Noble Construction Ltd",
    "destination_port": "Port Victoria, Seychelles",
    "freight_type": "Sea Freight",
    "buyer_contact": "procurement@sahaj.sc",
    "generated_by": "Senior Sourcing Officer",
    "org_name": "Sahaj Holding Corp",
    "remark": "Official Request for Quotation. Technical datasheets and mill test certificates required with bid submission.",
    "show_budget": False,
    "company": {
        "name": "Sahaj Holding Corp",
        "address": "Victoria Commercial Center, Mahe, Seychelles",
        "tax_id": "TAX-SEY-99201",
        "phone": "+248 4 123 456",
        "email": "procurement@sahaj.sc",
    },
    "supplier": {
        "name": "Prospective Bidder / Supplier",
        "code": "VENDOR-INVITED",
        "contact_person": "Commercial / Quotation Dept",
        "email": "bids@supplier.com",
    },
    "supplier_name": "Prospective Bidder / Supplier",
    "items": [
        {
            "line_no": 1,
            "sku": "STL-BEAM-HEA200",
            "item_code": "STL-BEAM-HEA200",
            "description": "Structural Steel HEA 200 Beams (S275JR) 12m standard lengths",
            "quantity": 45.0,
            "quantity_requested": 45.0,
            "unit": "MT",
            "technical_specifications": "Grade S275JR compliant with EN 10025-2. Mill test certificates EN 10204 3.1 mandatory.",
            "notes": "Bundle strapped with waterproof tags.",
            "estimated_unit_price": 850.00,
            "estimated_total": 38250.00,
        },
        {
            "line_no": 2,
            "sku": "STL-PLT-12MM",
            "item_code": "STL-PLT-12MM",
            "description": "Hot Rolled Mild Steel Plates 12mm x 2000mm x 6000mm",
            "quantity": 25.0,
            "quantity_requested": 25.0,
            "unit": "MT",
            "technical_specifications": "Grade ASTM A36 / S275, shot blasted and shop primed.",
            "notes": "Anti-rust coating required for ocean freight.",
            "estimated_unit_price": 820.00,
            "estimated_total": 20500.00,
        },
        {
            "line_no": 3,
            "sku": "BLT-HEX-M24",
            "item_code": "BLT-HEX-M24",
            "description": "High Strength Hex Structural Bolts & Nuts M24x80 Grade 8.8",
            "quantity": 1200.0,
            "quantity_requested": 1200.0,
            "unit": "SETS",
            "technical_specifications": "Hot Dip Galvanized to ISO 10684 with 2 heavy flat washers per set.",
            "notes": "Packaged in heavy-duty wooden boxes.",
            "estimated_unit_price": 3.40,
            "estimated_total": 4080.00,
        },
        {
            "line_no": 4,
            "sku": "ELEC-CBL-4CX16",
            "item_code": "ELEC-CBL-4CX16",
            "description": "Armored Copper Power Cable XLPE/SWA/PVC 4 Core x 16 sq mm",
            "quantity": 600.0,
            "quantity_requested": 600.0,
            "unit": "METERS",
            "technical_specifications": "0.6/1kV rated, stranded copper conductor, compliant with BS 5467.",
            "notes": "Supplied on wooden drum with sealed end caps.",
            "estimated_unit_price": 14.50,
            "estimated_total": 8700.00,
        },
        {
            "line_no": 5,
            "sku": "PVC-PIPE-110",
            "item_code": "PVC-PIPE-110",
            "description": "Heavy Duty PVC Drainage & Conduit Pipes 110mm OD x 6m",
            "quantity": 180.0,
            "quantity_requested": 180.0,
            "unit": "PCS",
            "technical_specifications": "Class 4 (SN8 ring stiffness) with elastomeric rubber ring sockets.",
            "notes": "UV stabilized for tropical conditions.",
            "estimated_unit_price": 28.00,
            "estimated_total": 5040.00,
        },
    ],
    "total_items": 5,
    "instructions": [
        "Please provide firm quotation specifying Unit Price, Total Price, Currency, and Delivery Terms (CIF Port Victoria preferred).",
        "State manufacturer name, country of origin, and expected delivery lead time in calendar days.",
        "Quotations must be submitted via email to procurement@sahaj.sc prior to the closing deadline.",
        "Prices must remain fixed and valid for at least 30 calendar days from the bid submission date.",
        "Include technical data sheets and material compliance certifications with your offer.",
    ],
}


@register_resolver(
    key="sourcing_rfq",
    name="Sourcing Request for Quotation (RFQ)",
    category="ORDERS",
    entity_type="RFQ",
    description="Resolves material procurement requisitions, technical item specifications, submission deadlines, and bidding instructions for suppliers.",
    schema_meta=RFQ_SCHEMA_META,
    sample_context=RFQ_SAMPLE_CONTEXT,
    print_permissions=["Print_PurchaseOrder", "View_RFQ", "Send_RFQ"],
)
def resolve_sourcing_rfq(
    entity_id: Any,
    db: Session,
    org_context: OrgContext,
    user: User,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    from Model.containermgmt.Orders.PurchaseOrder import PurchaseOrder

    query = db.query(PurchaseOrder).filter(PurchaseOrder.is_deleted == False)
    if str(entity_id).isdigit():
        query = query.filter((PurchaseOrder.id == int(entity_id)) | (PurchaseOrder.po_number == str(entity_id)))
    else:
        query = query.filter(PurchaseOrder.po_number == str(entity_id))

    po = apply_org_filter(query, PurchaseOrder, org_context).first()
    if not po:
        raise HTTPException(status_code=404, detail=f"Sourcing RFQ '{entity_id}' not found or access denied.")

    params = params or {}
    can_financial = is_financial_user(user, org_context)
    # Default: hide budget for vendor-facing RFQ unless explicitly requested and permitted
    show_budget = bool(params.get("show_budget", False)) and can_financial
    can_vendor = can_view_supplier_user(user, org_context)

    company_data = _resolve_company_profile(db, po.org_id)

    supplier_data = {}
    if can_vendor and po.supplier_rel:
        sup = po.supplier_rel
        supplier_data = {
            "name": getattr(sup, "company_name", None) or getattr(sup, "supplier_name", None) or getattr(sup, "Supplier", None) or po.company,
            "code": getattr(sup, "supplier_code", None),
            "contact_person": getattr(sup, "contact_person", None),
            "email": getattr(sup, "email", None),
            "phone": getattr(sup, "phone", None),
            "address": getattr(sup, "address", None),
        }
    else:
        supplier_data = {
            "name": po.company or "Invited Prospective Bidder",
            "code": None,
            "contact_person": None,
            "email": None,
            "phone": None,
            "address": None,
        }

    items_list = []
    line_no = 1
    total_est = Decimal("0.00")
    for item in po.items:
        if getattr(item, "is_deleted", False):
            continue
        item_qty = Decimal(str(item.quantity_ordered or 0))
        unit_p = Decimal(str(item.unit_price or 0))
        line_t = Decimal(str(item.total_price or (item_qty * unit_p)))
        total_est += line_t

        item_dict = {
            "line_no": line_no,
            "sku": item.item_code,
            "item_code": item.item_code,
            "description": item.description,
            "quantity": float(item_qty),
            "quantity_requested": float(item_qty),
            "unit": item.unit or "PCS",
            "technical_specifications": item.notes or "",
            "notes": item.notes,
            "estimated_unit_price": float(unit_p) if show_budget else None,
            "estimated_total": float(line_t) if show_budget else None,
        }
        items_list.append(item_dict)
        line_no += 1

    return {
        "rfq_number": po.po_number,
        "po_number": po.po_number,
        "po_nce": po.po_nce,
        "doc_type": po.doc_type or "RFQ",
        "status": po.status,
        "status_label": po.status_label or po.status,
        "lifecycle_stage": po.lifecycle_stage or "SOURCING",
        "issue_date": _clean_val(po.order_mail_date) or org_today_iso(db, org_context),
        "rfq_date": _clean_val(po.order_mail_date) or org_today_iso(db, org_context),
        "due_date": _clean_val(po.eta_date) or "As specified in invitation",
        "eta_date": _clean_val(po.eta_date),
        "report_date": org_today_iso(db, org_context),
        "currency": po.currency or "USD",
        "consignee": po.consignee,
        "consignee_name": po.consignee,
        "destination_port": getattr(po, "destination_port", None) or "Port Victoria, Seychelles",
        "freight_type": po.freight_type or "Sea Freight",
        "buyer_contact": company_data.get("email"),
        "generated_by": getattr(user, "username", "System"),
        "org_name": company_data.get("name"),
        "remark": po.remark or "Please submit best commercial offer in accordance with attached specifications.",
        "show_budget": show_budget,
        "company": company_data,
        "supplier": supplier_data,
        "supplier_name": supplier_data.get("name"),
        "items": items_list,
        "total_items": len(items_list),
        "estimated_budget_total": float(total_est) if show_budget else None,
        "instructions": company_data.get("default_terms", {}).get("rfq") or [
            "Please provide firm quotation specifying Unit Price, Total Price, Currency, and Delivery Terms (CIF Port Victoria preferred).",
            "State manufacturer name, country of origin, and expected delivery lead time in calendar days.",
            f"Quotations must be submitted to {company_data.get('email') or 'the issuing organisation'} prior to the closing deadline.",
            "Prices must remain fixed and valid for at least 30 calendar days from the bid submission date.",
            "Include technical data sheets and material compliance certifications with your offer.",
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# 5. Vendor Quote & Commercial Bid Evaluation Resolver
# ─────────────────────────────────────────────────────────────────────────────

QUOTE_COMPARISON_SCHEMA_META = {
    "rfq_number": {"type": "string", "description": "RFQ / Requisition reference", "example": "RFQ-2026-0089"},
    "title": {"type": "string", "description": "Comparison report title", "example": "Commercial Bid Evaluation & Price Comparison"},
    "comparison_date": {"type": "string", "description": "Date comparison generated", "example": "2026-03-28"},
    "generated_by": {"type": "string", "description": "User who compiled evaluation", "example": "Lead Procurement Officer"},
    "currency": {"type": "string", "description": "Base comparison currency", "example": "USD"},
    "org_name": {"type": "string", "description": "Organization name", "example": "Sahaj Holding Corp"},
    "show_financials": {"type": "boolean", "description": "True if user has permission to see financial comparison"},
    "vendors": {
        "type": "array",
        "description": "Summary profile of participating suppliers",
        "item_fields": {
            "vendor_id": {"type": "number", "example": 101},
            "vendor_name": {"type": "string", "example": "Apex Industrial Supplies Ltd"},
            "quote_reference": {"type": "string", "example": "AIS-Q-8821"},
            "quote_date": {"type": "string", "example": "2026-03-24"},
            "valid_until": {"type": "string", "example": "2026-04-24"},
            "total_quoted_amount": {"type": "number", "example": 68450.00},
            "currency": {"type": "string", "example": "USD"},
            "lead_time_days": {"type": "number", "example": 18},
            "shipping_terms": {"type": "string", "example": "CIF Port Victoria"},
            "payment_terms": {"type": "string", "example": "30% Advance, 70% vs BL"},
            "rank": {"type": "number", "example": 2},
            "status": {"type": "string", "example": "PENDING"},
            "score_notes": {"type": "string", "example": "Fastest delivery lead time, high compliance."},
        },
    },
    "matrix_rows": {
        "type": "array",
        "description": "Side-by-side line item pricing matrix across all bidders",
        "item_fields": {
            "item_code": {"type": "string", "example": "STL-BEAM-HEA200"},
            "description": {"type": "string", "example": "Structural Steel HEA 200 Beams 12m length"},
            "quantity": {"type": "number", "example": 45.0},
            "unit": {"type": "string", "example": "MT"},
            "lowest_unit_price": {"type": "number", "example": 820.00},
            "lowest_vendor_name": {"type": "string", "example": "Global Steel & Metals Corp"},
            "quotes": {
                "type": "array",
                "description": "Quotes for this specific line item per vendor",
                "item_fields": {
                    "vendor_id": {"type": "number", "example": 101},
                    "vendor_name": {"type": "string", "example": "Apex Industrial Supplies Ltd"},
                    "unit_price": {"type": "number", "example": 850.00},
                    "total_price": {"type": "number", "example": 38250.00},
                    "lead_time_days": {"type": "number", "example": 18},
                    "availability": {"type": "string", "example": "AVAILABLE"},
                    "is_awarded": {"type": "boolean", "example": False},
                    "notes": {"type": "string", "example": "Ex-stock warehouse"},
                },
            },
        },
    },
    "summary": {
        "type": "object",
        "description": "Comparative award and variance summary",
        "item_fields": {
            "total_items": {"type": "number", "example": 4},
            "total_vendors": {"type": "number", "example": 3},
            "recommended_vendor": {"type": "string", "example": "Global Steel & Metals Corp"},
            "lowest_vendor_total": {"type": "number", "example": 64200.00},
            "highest_vendor_total": {"type": "number", "example": 71800.00},
            "potential_savings": {"type": "number", "example": 7600.00},
        },
    },
}

QUOTE_COMPARISON_SAMPLE_CONTEXT = {
    "rfq_number": "RFQ-2026-0089",
    "po_number": "RFQ-2026-0089",
    "title": "Commercial Bid Evaluation & Vendor Price Comparison Matrix",
    "comparison_date": "2026-03-28",
    "generated_by": "Senior Sourcing Officer",
    "currency": "USD",
    "org_name": "Sahaj Holding Corp",
    "show_financials": True,
    "vendors": [
        {
            "vendor_id": 1,
            "vendor_name": "Global Steel & Metals Corp",
            "quote_reference": "GSM-2026-042",
            "quote_date": "2026-03-25",
            "valid_until": "2026-04-25",
            "total_quoted_amount": 64200.00,
            "currency": "USD",
            "lead_time_days": 24,
            "shipping_terms": "CIF Port Victoria",
            "payment_terms": "20% Adv, 80% Cad",
            "rank": 1,
            "status": "RECOMMENDED",
            "score_notes": "Lowest aggregate price ($64,200). Verified mill origin.",
        },
        {
            "vendor_id": 2,
            "vendor_name": "Apex Industrial Supplies Ltd",
            "quote_reference": "AIS-Q-8821",
            "quote_date": "2026-03-24",
            "valid_until": "2026-04-20",
            "total_quoted_amount": 68450.00,
            "currency": "USD",
            "lead_time_days": 18,
            "shipping_terms": "CIF Port Victoria",
            "payment_terms": "30% Adv, 70% BL",
            "rank": 2,
            "status": "COMPLIANT",
            "score_notes": "Fastest lead time (18 days). Established warranty track record.",
        },
        {
            "vendor_id": 3,
            "vendor_name": "Prime Horizon Trading FZE",
            "quote_reference": "PHT-9011-REV",
            "quote_date": "2026-03-26",
            "valid_until": "2026-04-30",
            "total_quoted_amount": 71800.00,
            "currency": "USD",
            "lead_time_days": 14,
            "shipping_terms": "FOB Dubai",
            "payment_terms": "100% LC at sight",
            "rank": 3,
            "status": "HIGHER_PRICE",
            "score_notes": "Prompt air/sea dispatch available, but freight excluded in FOB basis.",
        },
    ],
    "matrix_rows": [
        {
            "item_code": "STL-BEAM-HEA200",
            "description": "Structural Steel HEA 200 Beams 12m length",
            "quantity": 45.0,
            "unit": "MT",
            "lowest_unit_price": 820.00,
            "lowest_vendor_name": "Global Steel & Metals Corp",
            "quotes": [
                {
                    "vendor_id": 1,
                    "vendor_name": "Global Steel & Metals Corp",
                    "unit_price": 820.00,
                    "total_price": 36900.00,
                    "lead_time_days": 24,
                    "availability": "AVAILABLE",
                    "is_awarded": True,
                    "notes": "Grade S275JR",
                },
                {
                    "vendor_id": 2,
                    "vendor_name": "Apex Industrial Supplies Ltd",
                    "unit_price": 850.00,
                    "total_price": 38250.00,
                    "lead_time_days": 18,
                    "availability": "AVAILABLE",
                    "is_awarded": False,
                    "notes": "European mill stock",
                },
                {
                    "vendor_id": 3,
                    "vendor_name": "Prime Horizon Trading FZE",
                    "unit_price": 890.00,
                    "total_price": 40050.00,
                    "lead_time_days": 14,
                    "availability": "AVAILABLE",
                    "is_awarded": False,
                    "notes": "Ready in Jebel Ali",
                },
            ],
        },
        {
            "item_code": "STL-PLT-12MM",
            "description": "Hot Rolled Mild Steel Plates 12mm x 2000mm x 6000mm",
            "quantity": 25.0,
            "unit": "MT",
            "lowest_unit_price": 780.00,
            "lowest_vendor_name": "Global Steel & Metals Corp",
            "quotes": [
                {
                    "vendor_id": 1,
                    "vendor_name": "Global Steel & Metals Corp",
                    "unit_price": 780.00,
                    "total_price": 19500.00,
                    "lead_time_days": 24,
                    "availability": "AVAILABLE",
                    "is_awarded": True,
                    "notes": "Shot blasted & primed",
                },
                {
                    "vendor_id": 2,
                    "vendor_name": "Apex Industrial Supplies Ltd",
                    "unit_price": 810.00,
                    "total_price": 20250.00,
                    "lead_time_days": 18,
                    "availability": "AVAILABLE",
                    "is_awarded": False,
                    "notes": "Standard mill finish",
                },
                {
                    "vendor_id": 3,
                    "vendor_name": "Prime Horizon Trading FZE",
                    "unit_price": 840.00,
                    "total_price": 21000.00,
                    "lead_time_days": 14,
                    "availability": "AVAILABLE",
                    "is_awarded": False,
                    "notes": "Ready warehouse stock",
                },
            ],
        },
        {
            "item_code": "BLT-HEX-M24",
            "description": "High Strength Hex Structural Bolts & Nuts M24x80 Gr 8.8",
            "quantity": 1200.0,
            "unit": "SETS",
            "lowest_unit_price": 3.10,
            "lowest_vendor_name": "Global Steel & Metals Corp",
            "quotes": [
                {
                    "vendor_id": 1,
                    "vendor_name": "Global Steel & Metals Corp",
                    "unit_price": 3.10,
                    "total_price": 3720.00,
                    "lead_time_days": 20,
                    "availability": "AVAILABLE",
                    "is_awarded": True,
                    "notes": "Hot Dip Galv ISO 10684",
                },
                {
                    "vendor_id": 2,
                    "vendor_name": "Apex Industrial Supplies Ltd",
                    "unit_price": 3.40,
                    "total_price": 4080.00,
                    "lead_time_days": 15,
                    "availability": "AVAILABLE",
                    "is_awarded": False,
                    "notes": "Zinc flaked finish",
                },
                {
                    "vendor_id": 3,
                    "vendor_name": "Prime Horizon Trading FZE",
                    "unit_price": 3.80,
                    "total_price": 4560.00,
                    "lead_time_days": 10,
                    "availability": "AVAILABLE",
                    "is_awarded": False,
                    "notes": "Electro-galvanized",
                },
            ],
        },
        {
            "item_code": "PVC-PIPE-110",
            "description": "Heavy Duty PVC Drainage Pipes 110mm OD x 6m",
            "quantity": 180.0,
            "unit": "PCS",
            "lowest_unit_price": 22.65,
            "lowest_vendor_name": "Global Steel & Metals Corp",
            "quotes": [
                {
                    "vendor_id": 1,
                    "vendor_name": "Global Steel & Metals Corp",
                    "unit_price": 22.67,
                    "total_price": 4080.00,
                    "lead_time_days": 20,
                    "availability": "AVAILABLE",
                    "is_awarded": True,
                    "notes": "Class 4 SN8",
                },
                {
                    "vendor_id": 2,
                    "vendor_name": "Apex Industrial Supplies Ltd",
                    "unit_price": 32.61,
                    "total_price": 5870.00,
                    "lead_time_days": 18,
                    "availability": "AVAILABLE",
                    "is_awarded": False,
                    "notes": "Heavy gauge socketed",
                },
                {
                    "vendor_id": 3,
                    "vendor_name": "Prime Horizon Trading FZE",
                    "unit_price": 34.39,
                    "total_price": 6190.00,
                    "lead_time_days": 12,
                    "availability": "AVAILABLE",
                    "is_awarded": False,
                    "notes": "Immediate container pack",
                },
            ],
        },
    ],
    "summary": {
        "total_items": 4,
        "total_vendors": 3,
        "recommended_vendor": "Global Steel & Metals Corp",
        "lowest_vendor_total": 64200.00,
        "highest_vendor_total": 71800.00,
        "potential_savings": 7600.00,
        "awarded_vendor": "Global Steel & Metals Corp",
    },
}


@register_resolver(
    key="quote_comparison",
    name="Vendor Quote & Commercial Bid Evaluation",
    category="ORDERS",
    entity_type="QuoteComparison",
    description="Resolves comparative supplier bid matrices, line-by-line item quotations, lowest bidder highlights, lead times, and commercial award selections.",
    schema_meta=QUOTE_COMPARISON_SCHEMA_META,
    sample_context=QUOTE_COMPARISON_SAMPLE_CONTEXT,
    print_permissions=["Compare_Quote", "View_VendorQuote"],
)
def resolve_quote_comparison(
    entity_id: Any,
    db: Session,
    org_context: OrgContext,
    user: User,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    from Model.containermgmt.Orders.PurchaseOrder import PurchaseOrder
    from Model.containermgmt.Orders.VendorQuote import VendorQuote
    from Model.containermgmt.Orders.VendorQuoteItem import VendorQuoteItem

    query = db.query(PurchaseOrder).filter(PurchaseOrder.is_deleted == False)
    if str(entity_id).isdigit():
        query = query.filter((PurchaseOrder.id == int(entity_id)) | (PurchaseOrder.po_number == str(entity_id)))
    else:
        query = query.filter(PurchaseOrder.po_number == str(entity_id))

    po = apply_org_filter(query, PurchaseOrder, org_context).first()
    if not po:
        raise HTTPException(status_code=404, detail=f"Order / RFQ '{entity_id}' not found or access denied.")

    can_financial = is_financial_user(user, org_context)
    can_vendor = can_view_supplier_user(user, org_context)

    # Fetch quotes for this PO/RFQ
    quotes_query = db.query(VendorQuote).filter(
        VendorQuote.po_id == po.id,
        VendorQuote.is_deleted == False,
    ).order_by(VendorQuote.rank.asc().nullslast(), VendorQuote.total_quoted_amount.asc())
    vendor_quotes = quotes_query.all()

    vendors_list = []
    vendor_ids = []
    for q in vendor_quotes:
        v_name = "Supplier"
        if can_vendor and q.supplier:
            v_name = getattr(q.supplier, "company_name", None) or getattr(q.supplier, "supplier_name", None) or getattr(q.supplier, "Supplier", None) or f"Vendor #{q.supplier_id}"
        elif not can_vendor:
            v_name = f"Bidder #{len(vendors_list) + 1} (Confidential)"

        vendor_ids.append(q.id)
        vendors_list.append({
            "vendor_id": q.id,
            "supplier_id": q.supplier_id,
            "vendor_name": v_name,
            "quote_reference": q.quote_reference or f"Q-{q.id}",
            "quote_date": _clean_val(q.quote_date),
            "valid_until": _clean_val(q.valid_until),
            "total_quoted_amount": float(q.total_quoted_amount or 0) if can_financial else None,
            "currency": q.currency or po.currency or "USD",
            "lead_time_days": q.delivery_lead_time_days,
            "shipping_terms": q.shipping_terms,
            "payment_terms": q.payment_terms,
            "rank": q.rank,
            "status": q.status,
            "score_notes": q.score_notes,
        })

    # Build comparative matrix by PO items
    matrix_rows = []
    lowest_overall_total = None
    highest_overall_total = None
    recommended_vendor = None

    if vendors_list and can_financial:
        valid_totals = [v["total_quoted_amount"] for v in vendors_list if v["total_quoted_amount"] is not None]
        if valid_totals:
            lowest_overall_total = min(valid_totals)
            highest_overall_total = max(valid_totals)
            rec = next((v for v in vendors_list if v["total_quoted_amount"] == lowest_overall_total), None)
            if rec:
                recommended_vendor = rec["vendor_name"]

    for po_item in po.items:
        if getattr(po_item, "is_deleted", False):
            continue

        item_qty = float(po_item.quantity_ordered or 0)
        quotes_for_item = []
        lowest_unit_price = None
        lowest_vendor_name = None

        for v in vendors_list:
            q_id = v["vendor_id"]
            # Find matching quote item
            q_item = db.query(VendorQuoteItem).filter(
                VendorQuoteItem.vendor_quote_id == q_id,
                VendorQuoteItem.po_item_id == po_item.id,
                VendorQuoteItem.is_deleted == False,
            ).first()

            if not q_item:
                # Try matching by item_code or description
                q_item = db.query(VendorQuoteItem).filter(
                    VendorQuoteItem.vendor_quote_id == q_id,
                    VendorQuoteItem.item_code == po_item.item_code,
                    VendorQuoteItem.is_deleted == False,
                ).first()

            if q_item:
                unit_p = float(q_item.unit_price or 0) if can_financial else None
                tot_p = float(q_item.total_price or 0) if can_financial else None
                if can_financial and unit_p is not None:
                    if lowest_unit_price is None or unit_p < lowest_unit_price:
                        lowest_unit_price = unit_p
                        lowest_vendor_name = v["vendor_name"]

                quotes_for_item.append({
                    "vendor_id": v["vendor_id"],
                    "vendor_name": v["vendor_name"],
                    "unit_price": unit_p,
                    "total_price": tot_p,
                    "lead_time_days": q_item.lead_time_days,
                    "availability": q_item.availability or "AVAILABLE",
                    "is_awarded": bool(q_item.is_awarded),
                    "notes": q_item.notes or "",
                })
            else:
                quotes_for_item.append({
                    "vendor_id": v["vendor_id"],
                    "vendor_name": v["vendor_name"],
                    "unit_price": None,
                    "total_price": None,
                    "lead_time_days": None,
                    "availability": "NO_QUOTE",
                    "is_awarded": False,
                    "notes": "No quote provided",
                })

        matrix_rows.append({
            "item_code": po_item.item_code,
            "description": po_item.description,
            "quantity": item_qty,
            "unit": po_item.unit or "PCS",
            "lowest_unit_price": lowest_unit_price,
            "lowest_vendor_name": lowest_vendor_name,
            "quotes": quotes_for_item,
        })

    potential_savings = None
    if lowest_overall_total is not None and highest_overall_total is not None:
        potential_savings = highest_overall_total - lowest_overall_total

    return {
        "rfq_number": po.po_number,
        "po_number": po.po_number,
        "title": f"Commercial Bid Evaluation & Vendor Price Comparison — {po.po_number}",
        "comparison_date": org_today_iso(db, org_context),
        "generated_by": getattr(user, "username", "System"),
        "currency": po.currency or "USD",
        "org_name": "Sahaj Holding Corp",
        "show_financials": can_financial,
        "vendors": vendors_list,
        "matrix_rows": matrix_rows,
        "summary": {
            "total_items": len(matrix_rows),
            "total_vendors": len(vendors_list),
            "recommended_vendor": recommended_vendor or (vendors_list[0]["vendor_name"] if vendors_list else "None"),
            "lowest_vendor_total": lowest_overall_total,
            "highest_vendor_total": highest_overall_total,
            "potential_savings": potential_savings,
        },
    }


def resolve_report_data(
    resolver_key: str,
    entity_id: Optional[Any],
    db: Session,
    org_context: OrgContext,
    user: User,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Main entry point for resolving report data context.
    If entity_id is 0 or None, returns sample_context for editor live previews.
    """
    resolver_def = get_resolver(resolver_key)
    if not entity_id or str(entity_id) in ["0", "null", "undefined"]:
        # Return realistic sample context with any user overrides
        sample = dict(resolver_def.sample_context)
        if params:
            sample.update(params)
        return sample

    return resolver_def.fn(entity_id, db, org_context, user, params)

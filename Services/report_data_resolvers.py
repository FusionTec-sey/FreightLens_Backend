"""
Services/report_data_resolvers.py
Data Resolver Registry and Built-in Resolvers for the Report & Print Template System.
Resolvers query the database with multi-tenant row isolation and permission-aware field redaction.
"""
import logging
from typing import Dict, Any, Optional, Callable, List
from datetime import datetime, date
from decimal import Decimal
from fastapi import HTTPException
from sqlalchemy.orm import Session

from Utils.org_filter import OrgContext, apply_org_filter
from Model.Credentials.users import User
from Model.Credentials.Organisation import Organisation
from auth.security_guards import is_financial_user, can_view_supplier_user

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
    ):
        self.key = key
        self.name = name
        self.category = category
        self.entity_type = entity_type
        self.description = description
        self.fn = fn
        self.schema_meta = schema_meta
        self.sample_context = sample_context


_RESOLVER_REGISTRY: Dict[str, ResolverDefinition] = {}


def register_resolver(
    key: str,
    name: str,
    category: str,
    entity_type: str,
    description: str,
    schema_meta: Dict[str, Any],
    sample_context: Dict[str, Any],
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

    # Fetch Issuing Organisation branding
    company_data = {
        "name": "Sahaj Holding Corp",
        "address": "Victoria, Mahe, Seychelles",
        "tax_id": None,
        "phone": None,
        "email": None,
    }
    if po.org_id:
        org_rec = db.query(Organisation).filter(Organisation.id == po.org_id).first()
        if org_rec:
            company_data["name"] = org_rec.name or company_data["name"]

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
        "report_date": date.today().isoformat(),
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

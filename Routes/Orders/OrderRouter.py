import logging
import io
from datetime import datetime, date, timedelta
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload, selectinload
from sqlalchemy import or_, and_, desc, asc, func
import math
from Services.search_service import search_orders_with_total, sync_order_document, remove_order_document

from Model.db import get_db
from Model.containermgmt.Orders.PurchaseOrder import PurchaseOrder
from Model.containermgmt.Orders.OrderStatus import OrderStatus
from Model.containermgmt.Orders.POItem import POItem
from Model.containermgmt.Orders.OrderDocument import OrderDocument
from Model.containermgmt.Orders.VendorQuote import VendorQuote
from Model.containermgmt.Orders.DefectReport import DefectReport, DefectImage
from Model.containermgmt.Orders.OrderPayment import OrderPayment
from Model.containermgmt.Orders.OrderShipment import OrderShipment
from Model.containermgmt.Orders.OrderStatusHistory import OrderStatusHistory
from Model.containermgmt.Orders.StoreRequest import StoreRequest, StoreRequestItem
from Model.containermgmt.Orders.Notification import Notification
from Model.containermgmt.Cinfo.Supplier import Supplier
from Model.containermgmt.Container.BillOfLanding import BillOfLanding
from Model.containermgmt.Container.ContainerDetails import ContainerDetails
from Model.Credentials.users import User
from auth.dependencies import get_current_user, get_org_context
from auth.security_guards import (
    is_financial_user,
    can_view_supplier_user,
    has_permission,
    require_permission,
    require_financial_access,
)
from Utils.org_filter import OrgContext, apply_org_filter
from Utils.blob_storage import blob_storage
from Utils.reportGenerator import generate_defect_report_pdf

logger = logging.getLogger("containerMgmt.orders")

OrderRouter = APIRouter(prefix="/orders", tags=["Purchase Orders"])

def is_accounts_user(user: User, org_context: OrgContext) -> bool:
    return is_financial_user(user, org_context)

def can_user_view_supplier(user: User, org_context: OrgContext) -> bool:
    return can_view_supplier_user(user, org_context)

def order_to_dict(order: PurchaseOrder, is_accounts: bool = True, can_view_supplier: bool = True) -> dict:
    doc_type = (getattr(order, "doc_type", "PO") or "PO").upper()
    is_rfq = (doc_type == "RFQ")

    # Authoritative financial authorization:
    # 1. RFQ documents NEVER expose purchasing prices, line totals, advance/balance, or payment records to ANY role.
    # 2. Purchase Orders (PO) only expose financial figures to authorized accounts/financial users.
    can_view_financials = is_accounts and (not is_rfq)

    is_awarded = (order.lifecycle_stage or "").upper() in ["QUOTE_APPROVED", "PO_ISSUED", "ORDERED", "RECEIVED", "COMPLETED"]

    # STRICT VENDOR SECURITY:
    # 1. Sourcing RFQ documents are material requisitions: NEVER expose vendor names, candidate vendors, or supplier IDs.
    # 2. Purchase Orders (PO) only expose vendor/supplier details to users with verified supplier clearance.
    supplier_name = None
    if not is_rfq and can_view_supplier:
        supplier_name = order.company
        if order.supplier_rel and order.supplier_rel.name:
            supplier_name = order.supplier_rel.name

    status_name = order.status_label or order.status
    status_progress = 50
    status_color = "bg-blue-500"
    badge_color = "bg-blue-50 text-blue-800 border-blue-200"

    if order.order_status_rel:
        status_name = order.order_status_rel.name
        status_progress = order.order_status_rel.progress
        status_color = order.order_status_rel.color
        badge_color = order.order_status_rel.badge_color or badge_color

    # Calculate authoritative financial values
    active_payments = [pm for pm in (order.payments or []) if not pm.is_deleted]
    active_payments_sum = sum(float(pm.amount or 0) for pm in active_payments)

    eff_advance = float(order.advance_amount) if order.advance_amount is not None else (active_payments_sum if active_payments else 0.0)
    if active_payments and (eff_advance == 0 or eff_advance is None):
        eff_advance = active_payments_sum

    eff_total = float(order.total_amount) if order.total_amount is not None else None
    eff_balance = float(order.balance_amount) if order.balance_amount is not None else (
        max(0.0, eff_total - eff_advance) if eff_total is not None else None
    )

    # Fulfillment rollup for Sourcing RFQs with child POs
    active_child_pos = [c for c in (getattr(order, "child_pos", None) or []) if not c.is_deleted]
    fulfillment_summary = None
    if is_rfq and is_awarded:
        STAGE_RANKS = {
            "COMPLETED": 100,
            "RECEIVED": 96,
            "ARRIVED": 92,
            "SHIPPED": 85,
            "PACKED": 78,
            "READY": 70,
            "IN_PRODUCTION": 55,
            "ORDERED": 40,
            "PO_ISSUED": 35,
            "SOURCING": 25,
            "SUBMITTED": 15,
            "DRAFT": 5,
        }
        if active_child_pos:
            sorted_by_progress = sorted(active_child_pos, key=lambda c: STAGE_RANKS.get(str(c.status).upper(), 30), reverse=True)
            primary_child = sorted_by_progress[0]
            
            child_etas = [c.eta_date for c in active_child_pos if c.eta_date]
            earliest_child_eta = min(child_etas) if child_etas else None

            child_status_counts = {}
            for c in active_child_pos:
                lbl = c.status_label or (c.order_status_rel.name if c.order_status_rel else c.status)
                child_status_counts[lbl] = child_status_counts.get(lbl, 0) + 1

            summary_parts = [f"{cnt} {st}" if len(active_child_pos) > 1 else st for st, cnt in child_status_counts.items()]
            summary_desc = ", ".join(summary_parts)

            primary_lbl = primary_child.status_label or (primary_child.order_status_rel.name if primary_child.order_status_rel else primary_child.status)
            fulfillment_summary = {
                "total_child_pos": len(active_child_pos),
                "primary_status": primary_child.status,
                "primary_status_label": primary_lbl,
                "primary_status_color": primary_child.order_status_rel.color if primary_child.order_status_rel else "bg-indigo-500",
                "primary_badge_color": primary_child.order_status_rel.badge_color if primary_child.order_status_rel else "bg-indigo-50 text-indigo-800 border-indigo-200 dark:bg-indigo-950/40 dark:text-indigo-300 dark:border-indigo-800",
                "primary_progress": primary_child.order_status_rel.progress if primary_child.order_status_rel else STAGE_RANKS.get(str(primary_child.status).upper(), 40),
                "summary_desc": summary_desc,
                "eta_date": earliest_child_eta.isoformat() if earliest_child_eta else None,
            }
        else:
            fulfillment_summary = {
                "total_child_pos": 0,
                "primary_status": "AWAITING_PO",
                "primary_status_label": "Awarded / Awaiting PO",
                "primary_status_color": "bg-emerald-500",
                "primary_badge_color": "bg-emerald-50 text-emerald-800 border-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-300 dark:border-emerald-800",
                "primary_progress": 35,
                "summary_desc": "Awarded - PO issuance pending",
                "eta_date": None,
            }

    raw_payment_status = (order.payment_status or "NONE").upper()
    payment_label = "Paid" if raw_payment_status in ["FULLY_PAID", "PAID"] else ("Part Paid" if raw_payment_status in ["PART_PAID", "ADVANCE_PAID"] else "Unpaid")
    payment_badge_color = (
        "bg-emerald-50 text-emerald-800 border-emerald-300 dark:bg-emerald-950/40 dark:text-emerald-300 dark:border-emerald-700"
        if raw_payment_status in ["FULLY_PAID", "PAID"]
        else (
            "bg-amber-50 text-amber-800 border-amber-300 dark:bg-amber-950/40 dark:text-amber-300 dark:border-amber-700"
            if raw_payment_status in ["PART_PAID", "ADVANCE_PAID"]
            else "bg-slate-100 text-slate-600 border-slate-300 dark:bg-slate-800 dark:text-slate-400 dark:border-slate-700"
        )
    )

    effective_eta = order.eta_date.isoformat() if order.eta_date else (
        fulfillment_summary["eta_date"] if (fulfillment_summary and fulfillment_summary.get("eta_date")) else None
    )

    res = {
        "id": order.id,
        "po_number": order.po_number,
        "po_nce": order.po_nce if can_view_financials else None,
        "request_id": order.request_id,
        "request_number": order.store_request.request_number if order.store_request else None,
        "supplier": order.supplier_id if (can_view_supplier and not is_rfq) else None,
        "company": supplier_name,
        "goods_description": order.goods_description,
        "material_ids": order.material_ids or [],
        "org_id": order.org_id,
        
        # Lifecycle and tracking dimensions
        "status_id": order.status_id,
        "status": order.status,
        "status_label": status_name,
        "status_progress": status_progress,
        "status_color": status_color,
        "badge_color": badge_color,
        
        # Procurement Lifecycle Stage (7-stage pipeline)
        "lifecycle_stage": order.lifecycle_stage or "DRAFT",
        "lifecycle_version": order.lifecycle_version or 1,
        "stage_version": getattr(order, "stage_version", 1) or 1,
        "lifecycle_locked": bool(order.lifecycle_locked),
        "selected_quote_id": order.selected_quote_id if can_view_financials else None,
        
        # Decoupled Operational Dimensions
        "payment_status": raw_payment_status,
        "payment_label": payment_label,
        "payment_badge_color": payment_badge_color,
        "production_status": order.production_status or "NOT_STARTED",
        "shipment_status": order.shipment_status or "NOT_SHIPPED",
        "receipt_status": order.receipt_status or "PENDING",

        # Fulfillment rollup for Sourcing view
        "fulfillment_summary": fulfillment_summary,

        # Financials (Accounts on PO only)
        "total_amount": eff_total if (eff_total is not None and can_view_financials) else None,
        "advance_amount": eff_advance if can_view_financials else None,
        "balance_amount": eff_balance if can_view_financials else None,
        "currency": order.currency or "USD",

        # Document classification & lineage: RFQ vs PO
        "doc_type": doc_type,
        "parent_rfq_id": getattr(order, "parent_rfq_id", None),
        "origin_rfq_number": getattr(order, "origin_rfq_number", None),
        "split_index": getattr(order, "split_index", None),
        "child_pos": [
            {
                "id": c.id,
                "po_number": c.po_number,
                "supplier_id": c.supplier_id if (can_view_supplier and not is_rfq) else None,
                "company": (c.company or (c.supplier_rel.name if c.supplier_rel else None)) if (can_view_supplier and not is_rfq) else None,
                "total_amount": float(c.total_amount or 0) if can_view_financials else None,
                "status": c.status,
                "status_label": c.status_label or (c.order_status_rel.name if c.order_status_rel else c.status),
                "status_color": c.order_status_rel.color if c.order_status_rel else "bg-blue-500",
                "badge_color": c.order_status_rel.badge_color if c.order_status_rel else "bg-blue-50 text-blue-800 border-blue-200 dark:bg-blue-950/40 dark:text-blue-300 dark:border-blue-800",
                "lifecycle_stage": c.lifecycle_stage,
                "payment_status": (c.payment_status or "NONE").upper(),
                "production_status": c.production_status or "NOT_STARTED",
                "shipment_status": c.shipment_status or "NOT_SHIPPED",
                "receipt_status": c.receipt_status or "PENDING",
                "eta_date": c.eta_date.isoformat() if c.eta_date else None,
                "currency": c.currency or "USD",
                "items_count": len([i for i in (c.items or []) if not i.is_deleted])
            }
            for c in active_child_pos
        ],

        # Legacy fields
        "sheet_type": order.sheet_type,
        "consignee": order.consignee,
        "year": order.year,
        "urgent_action": bool(order.urgent_action),
        
        # Milestone dates
        "order_mail_date": order.order_mail_date.isoformat() if order.order_mail_date else None,
        "quote_sent_date": order.quote_sent_date.isoformat() if order.quote_sent_date else None,
        "quote_received_date": order.quote_received_date.isoformat() if order.quote_received_date else None,
        "pi_confirmed_date": order.pi_confirmed_date.isoformat() if order.pi_confirmed_date else None,
        "payment_date": order.payment_date.isoformat() if order.payment_date and can_view_financials else None,
        "balance_payment_date": order.balance_payment_date.isoformat() if order.balance_payment_date and can_view_financials else None,
        "eta_date": effective_eta,
        "freight_type": order.freight_type or "Sea Freight",
        "remark": order.remark,
        "created_at": order.created_at.isoformat() if order.created_at else None,

        # Line items - prices strictly sanitized for RFQ or non-financial PO
        "items": [
            {
                "id": it.id,
                "product_id": it.product_id,
                "item_code": it.item_code,
                "description": it.description,
                "quantity_ordered": float(it.quantity_ordered or 0),
                "quantity_packed": float(it.quantity_packed or 0),
                "quantity_received": float(it.quantity_received or 0),
                "unit": it.unit,
                "unit_price": float(it.unit_price) if it.unit_price and can_view_financials else None,
                "total_price": float(it.total_price) if it.total_price and can_view_financials else None,
                "draft_unit_price": float(it.draft_unit_price) if it.draft_unit_price and can_view_financials else None,
                "approved_unit_price": float(it.approved_unit_price) if it.approved_unit_price and can_view_financials else None,
                "po_unit_price": float(it.po_unit_price) if it.po_unit_price and can_view_financials else None,
                "proforma_unit_price": float(it.proforma_unit_price) if it.proforma_unit_price and can_view_financials else None,
                "source_rfq_item_id": getattr(it, "source_rfq_item_id", None),
                "awarded_vendor_id": getattr(it, "awarded_vendor_id", None) if can_view_financials else None,
                "awarded_quote_id": getattr(it, "awarded_quote_id", None) if can_view_financials else None,
                "item_status": it.item_status or "ACTIVE",
                "revision_count": len([h for h in (it.history or []) if not h.is_deleted]),
                "notes": it.notes,
            }
            for it in (order.items or []) if not it.is_deleted
        ],

        # Linked shipments
        "shipments": [
            {
                "id": sh.id,
                "bill_of_lading_no": sh.bill_of_lading_no,
                "container_id": sh.container_id,
                "container_no": sh.container.container_no if sh.container else None,
                "arrival_date": sh.bill_of_lading.ArrivalDate.isoformat() if sh.bill_of_lading and sh.bill_of_lading.ArrivalDate else None,
                "shipment_status": sh.shipment_status,
                "notes": sh.notes,
            }
            for sh in (order.shipments or []) if not sh.is_deleted
        ],

        # Linked payments (Accounts on PO only)
        "payments": [
            {
                "id": pm.id,
                "payment_type": pm.payment_type,
                "amount": float(pm.amount or 0),
                "currency": pm.currency,
                "paid_date": pm.paid_date.isoformat() if pm.paid_date else None,
                "due_date": pm.due_date.isoformat() if pm.due_date else None,
                "status": pm.status,
                "payment_method": pm.payment_method,
                "reference_number": pm.reference_number,
                "notes": pm.notes,
                "created_at": pm.created_at.isoformat() if hasattr(pm, 'created_at') and pm.created_at else None,
            }
            for pm in (order.payments or []) if not pm.is_deleted
        ] if can_view_financials else [],

        # Documents
        "documents": [
            {
                "id": doc.id,
                "title": doc.title,
                "doc_type": doc.doc_type,
                "file_name": doc.file_name,
                "file_path": doc.file_path,
                "created_at": doc.created_at.isoformat() if doc.created_at else None,
            }
            for doc in (order.documents or []) if not doc.is_deleted and (not doc.is_confidential or is_accounts)
        ]
    }
    return res

@OrderRouter.get("")
@OrderRouter.get("/")
def list_orders(
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=100),
    sort_by: Optional[str] = Query(None),
    sort_dir: Optional[str] = Query("desc"),
    search: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    lifecycle_stage: Optional[str] = Query(None),
    doc_type: Optional[str] = Query(None),
    urgent_only: Optional[bool] = Query(False),
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    is_accounts = is_accounts_user(current_user, org_context)
    can_view_supp = can_user_view_supplier(current_user, org_context)
    can_view_rfq = has_permission(current_user, "View_RFQ") or is_accounts
    can_view_po = has_permission(current_user, "View_Order") or is_accounts

    if not can_view_rfq and not can_view_po:
        raise HTTPException(status_code=403, detail="Access forbidden: Missing order and RFQ view permissions.")

    offset = (page - 1) * limit

    # ── High-Performance Meilisearch Integration ──
    if search and search.strip():
        meili_filters = ["is_deleted = false"]
        if org_context and getattr(org_context, "org_id", None):
            meili_filters.append(f"org_id = {org_context.org_id}")

        if can_view_rfq and not can_view_po:
            meili_filters.append("doc_type = 'RFQ'")
        elif can_view_po and not can_view_rfq:
            meili_filters.append("doc_type = 'PO'")
        elif doc_type and doc_type != "ALL":
            req_doc = doc_type.upper()
            if req_doc in ["RFQ", "PO"]:
                meili_filters.append(f"doc_type = '{req_doc}'")

        if status and status != "ALL":
            meili_filters.append(f"(status = '{status}' OR status_label = '{status}')")
        if lifecycle_stage and lifecycle_stage != "ALL":
            meili_filters.append(f"lifecycle_stage = '{lifecycle_stage}'")
        if urgent_only:
            meili_filters.append("urgent_action = true")

        hits, total_count = search_orders_with_total(
            query_str=search.strip(),
            filters=meili_filters,
            limit=limit,
            offset=offset
        )

        if hits:
            hit_ids = [h["id"] for h in hits]
            orders = (
                db.query(PurchaseOrder)
                .options(
                    joinedload(PurchaseOrder.order_status_rel),
                    joinedload(PurchaseOrder.supplier_rel),
                    joinedload(PurchaseOrder.store_request),
                    selectinload(PurchaseOrder.items),
                    selectinload(PurchaseOrder.child_pos),
                    selectinload(PurchaseOrder.shipments).joinedload(OrderShipment.container),
                    selectinload(PurchaseOrder.shipments).joinedload(OrderShipment.bill_of_lading),
                    selectinload(PurchaseOrder.payments),
                    selectinload(PurchaseOrder.documents)
                )
                .filter(PurchaseOrder.id.in_(hit_ids))
                .all()
            )
            order_map = {o.id: o for o in orders}
            sorted_orders = [order_map[hid] for hid in hit_ids if hid in order_map]

            return {
                "items": [order_to_dict(o, is_accounts, can_view_supp) for o in sorted_orders],
                "total": total_count,
                "page": page,
                "limit": limit,
                "pages": math.ceil(total_count / limit) if total_count > 0 else 1
            }

    # ── Fallback Database Query with Filters & Sorting ──
    query = (
        db.query(PurchaseOrder)
        .options(
            joinedload(PurchaseOrder.order_status_rel),
            joinedload(PurchaseOrder.supplier_rel),
            joinedload(PurchaseOrder.store_request),
            selectinload(PurchaseOrder.items),
            selectinload(PurchaseOrder.child_pos),
            selectinload(PurchaseOrder.shipments).joinedload(OrderShipment.container),
            selectinload(PurchaseOrder.shipments).joinedload(OrderShipment.bill_of_lading),
            selectinload(PurchaseOrder.payments),
            selectinload(PurchaseOrder.documents)
        )
        .filter(PurchaseOrder.is_deleted == False)
    )

    query = apply_org_filter(query, PurchaseOrder, org_context)

    # Permission constraints on doc_type
    if can_view_rfq and not can_view_po:
        query = query.filter(PurchaseOrder.doc_type == "RFQ")
    elif can_view_po and not can_view_rfq:
        query = query.filter(PurchaseOrder.doc_type == "PO")

    # Document classification filter (RFQ vs PO)
    if doc_type and doc_type != "ALL":
        req_doc = doc_type.upper()
        if req_doc == "RFQ" and not can_view_rfq:
            return {"items": [], "total": 0, "page": page, "limit": limit, "pages": 1}
        if req_doc == "PO" and not can_view_po:
            return {"items": [], "total": 0, "page": page, "limit": limit, "pages": 1}
        query = query.filter(PurchaseOrder.doc_type == req_doc)

    # Search (SQL fallback)
    if search:
        s_term = f"%{search.strip()}%"
        search_clauses = [
            PurchaseOrder.po_number.ilike(s_term),
            PurchaseOrder.company.ilike(s_term),
            PurchaseOrder.goods_description.ilike(s_term),
        ]
        if is_accounts:
            search_clauses.append(PurchaseOrder.po_nce.ilike(s_term))
        query = query.filter(or_(*search_clauses))

    # Operational Status filter
    if status and status != "ALL":
        query = query.filter(
            or_(PurchaseOrder.status == status, PurchaseOrder.status_label == status)
        )

    # Procurement Lifecycle Stage filter
    if lifecycle_stage and lifecycle_stage != "ALL":
        query = query.filter(PurchaseOrder.lifecycle_stage == lifecycle_stage)

    # Urgent filter
    if urgent_only:
        query = query.filter(PurchaseOrder.urgent_action == True)

    total_count = query.count()

    ALLOWED_SORT = {
        "id": PurchaseOrder.id,
        "po_number": PurchaseOrder.po_number,
        "company": PurchaseOrder.company,
        "status": PurchaseOrder.status,
        "lifecycle_stage": PurchaseOrder.lifecycle_stage,
        "created_at": PurchaseOrder.created_at,
        "total_amount": PurchaseOrder.total_amount
    }
    sort_column = ALLOWED_SORT.get(sort_by, PurchaseOrder.id)
    if sort_dir == "asc":
        query = query.order_by(asc(sort_column))
    else:
        query = query.order_by(desc(sort_column))

    orders = query.offset(offset).limit(limit).all()
    return {
        "items": [order_to_dict(o, is_accounts, can_view_supp) for o in orders],
        "total": total_count,
        "page": page,
        "limit": limit,
        "pages": math.ceil(total_count / limit) if total_count > 0 else 1
    }

# ── Document Endpoints (Must be before /{order_id}) ───────────────────────────
# ── Document Endpoints (Must be before /{order_id}) ───────────────────────────
@OrderRouter.get("/documents/config")
async def get_document_config(
    space: Optional[str] = Query(None, description="Stage / space filter: SOURCING, ORDER, PAYMENT, SHIPPING, DEFECTS"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        from Model.containermgmt.MasterData.DocumentType import MasterDocumentType
        q = db.query(MasterDocumentType).filter(
            MasterDocumentType.is_active == True,
            MasterDocumentType.is_deleted == False
        )
        rows = q.order_by(MasterDocumentType.display_order.asc(), MasterDocumentType.id.asc()).all()
        if space:
            target_space = space.strip().upper()
            filtered = []
            for r in rows:
                spaces = [str(s).upper() for s in (r.applicable_spaces or [])]
                if not spaces or target_space in spaces:
                    filtered.append(r)
            rows = filtered

        if rows:
            return {
                "document_types": [
                    {
                        "value": r.code,
                        "label": r.name,
                        "description": r.description,
                        "applicable_spaces": r.applicable_spaces or [],
                        "can_upload": True
                    }
                    for r in rows
                ]
            }
    except Exception as e:
        logger.warning(f"Failed to query master_document_types, falling back to defaults: {e}")

    return {
        "document_types": [
            {"value": "payment_proof", "label": "Bank TT / Swift Slip / Payment Proof", "can_upload": True},
            {"value": "quotation", "label": "Vendor Quotation / Proforma Invoice", "can_upload": True},
            {"value": "defect_evidence", "label": "Defect Evidence / Photo", "can_upload": True},
            {"value": "defect_resolution", "label": "Resolution Document", "can_upload": True},
            {"value": "credit_note", "label": "Credit Note", "can_upload": True},
            {"value": "inspection_report", "label": "Inspection Report", "can_upload": True},
            {"value": "invoice", "label": "Commercial Invoice", "can_upload": True},
            {"value": "packing_list", "label": "Packing List", "can_upload": True},
            {"value": "bill_of_lading", "label": "Bill of Lading", "can_upload": True},
            {"value": "other", "label": "Other Document", "can_upload": True},
        ]
    }

@OrderRouter.get("/documents")
async def list_documents(
    defect_report_id: Optional[int] = Query(None),
    purchase_order_id: Optional[int] = Query(None),
    request_id: Optional[int] = Query(None),
    payment_id: Optional[int] = Query(None),
    vendor_quote_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    results = []
    if payment_id:
        doc_q = db.query(OrderDocument).filter(
            ((OrderDocument.payment_id == payment_id) | 
             ((OrderDocument.entity_type == "PAYMENT") & (OrderDocument.entity_id == payment_id))),
            OrderDocument.is_deleted == False
        ).order_by(OrderDocument.created_at.desc())
        for doc in doc_q.all():
            results.append({
                "id": str(doc.id),
                "original_name": doc.title or doc.file_name or f"payment_proof_{doc.id}",
                "document_type": doc.doc_type,
                "document_label": "Payment Proof",
                "file_path": doc.file_path,
                "file_size": doc.file_size,
                "mime_type": doc.mime_type,
                "uploaded_by": "Accounts",
                "uploaded_at": doc.created_at.isoformat() if doc.created_at else datetime.utcnow().isoformat(),
            })
        return results

    if vendor_quote_id:
        doc_q = db.query(OrderDocument).filter(
            ((OrderDocument.vendor_quote_id == vendor_quote_id) |
             ((OrderDocument.entity_type == "VENDOR_QUOTE") & (OrderDocument.entity_id == vendor_quote_id))),
            OrderDocument.is_deleted == False
        ).order_by(OrderDocument.created_at.desc())
        for doc in doc_q.all():
            results.append({
                "id": str(doc.id),
                "original_name": doc.title or doc.file_name or f"quote_doc_{doc.id}",
                "document_type": doc.doc_type,
                "document_label": "Vendor Quote Attachment",
                "file_path": doc.file_path,
                "file_size": doc.file_size,
                "mime_type": doc.mime_type,
                "uploaded_by": "Buyer",
                "uploaded_at": doc.created_at.isoformat() if doc.created_at else datetime.utcnow().isoformat(),
            })
        return results

    if defect_report_id:
        def_q = db.query(DefectReport).filter(DefectReport.id == defect_report_id, DefectReport.is_deleted == False)
        def_q = apply_org_filter(def_q, DefectReport, org_context)
        report = def_q.first()
        if report:
            for img in (report.images or []):
                if not img.is_deleted:
                    results.append({
                        "id": str(img.id),
                        "original_name": img.caption or (img.file_path.split("/")[-1] if img.file_path else f"evidence_{img.id}.jpg"),
                        "document_type": "defect_evidence",
                        "document_label": img.caption or "Defect Evidence",
                        "file_path": img.file_path,
                        "uploaded_by": "Reporter",
                        "uploaded_at": report.created_at.isoformat() if report.created_at else datetime.utcnow().isoformat(),
                    })
    if purchase_order_id:
        doc_q = db.query(OrderDocument).filter(OrderDocument.po_id == purchase_order_id, OrderDocument.is_deleted == False)
        for doc in doc_q.all():
            results.append({
                "id": str(doc.id),
                "original_name": doc.title or doc.file_name or f"document_{doc.id}",
                "document_type": doc.doc_type,
                "document_label": doc.doc_type,
                "file_path": doc.file_path,
                "file_size": doc.file_size,
                "mime_type": doc.mime_type,
                "uploaded_by": "System",
                "uploaded_at": doc.created_at.isoformat() if doc.created_at else datetime.utcnow().isoformat(),
            })
    if request_id:
        doc_q = db.query(OrderDocument).filter(
            ((OrderDocument.entity_type == "STORE_REQUEST") & (OrderDocument.entity_id == request_id)) |
            (OrderDocument.po_id == request_id),
            OrderDocument.is_deleted == False
        )
        for doc in doc_q.all():
            results.append({
                "id": str(doc.id),
                "original_name": doc.title or doc.file_name or f"document_{doc.id}",
                "document_type": doc.doc_type,
                "document_label": doc.doc_type,
                "file_path": doc.file_path,
                "file_size": doc.file_size,
                "mime_type": doc.mime_type,
                "uploaded_by": "System",
                "uploaded_at": doc.created_at.isoformat() if doc.created_at else datetime.utcnow().isoformat(),
            })
    if not defect_report_id and not purchase_order_id and not request_id and not payment_id and not vendor_quote_id:
        doc_q = db.query(OrderDocument).filter(OrderDocument.is_deleted == False).order_by(OrderDocument.created_at.desc()).limit(100)
        for doc in doc_q.all():
            results.append({
                "id": str(doc.id),
                "original_name": doc.title or doc.file_name or f"document_{doc.id}",
                "document_type": doc.doc_type,
                "document_label": doc.doc_type,
                "file_path": doc.file_path,
                "file_size": doc.file_size,
                "mime_type": doc.mime_type,
                "uploaded_by": "System",
                "uploaded_at": doc.created_at.isoformat() if doc.created_at else datetime.utcnow().isoformat(),
            })
    return results

@OrderRouter.post("/documents")
async def upload_general_document(
    file: UploadFile = File(...),
    document_type: str = Form("other"),
    defect_report_id: Optional[int] = Form(None),
    purchase_order_id: Optional[int] = Form(None),
    request_id: Optional[int] = Form(None),
    payment_id: Optional[int] = Form(None),
    vendor_quote_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    file_bytes = await file.read()

    # 1. Payment Proof Upload
    if payment_id:
        pm = db.query(OrderPayment).filter(OrderPayment.id == payment_id, OrderPayment.is_deleted == False).first()
        if not pm:
            raise HTTPException(status_code=404, detail="Payment record not found")
        order = db.query(PurchaseOrder).filter(PurchaseOrder.id == pm.po_id, PurchaseOrder.is_deleted == False).first()
        po_number = (order.po_number if order and order.po_number else f"PO-{pm.po_id}").strip().replace("/", "-")
        
        folder = f"orders/{po_number}/payments/pay_{pm.id}_{pm.payment_type}"
        key = blob_storage.upload_file(
            file_obj=file_bytes,
            original_filename=file.filename,
            folder=folder
        )
        doc = OrderDocument(
            entity_type="PAYMENT",
            entity_id=pm.id,
            po_id=order.id if order else None,
            payment_id=pm.id,
            doc_type=document_type.upper() if document_type and document_type != "other" else f"{pm.payment_type}_PAYMENT_PROOF",
            title=file.filename,
            file_name=file.filename,
            file_path=key,
            file_size=len(file_bytes),
            mime_type=file.content_type,
            created_by=current_user.id
        )
        db.add(doc)
        db.flush()
        pm.evidence_doc_id = doc.id
        db.commit()
        db.refresh(doc)
        return {
            "success": True,
            "id": str(doc.id),
            "file_path": key,
            "file_name": doc.file_name,
            "doc_type": doc.doc_type,
            "payment_id": pm.id
        }

    # 2. Vendor Quote Attachment Upload
    if vendor_quote_id:
        quote = db.query(VendorQuote).filter(VendorQuote.id == vendor_quote_id, VendorQuote.is_deleted == False).first()
        if not quote:
            raise HTTPException(status_code=404, detail="Vendor quote record not found")
        order = db.query(PurchaseOrder).filter(PurchaseOrder.id == quote.po_id, PurchaseOrder.is_deleted == False).first()
        rfq_number = (order.po_number if order and order.po_number else f"RFQ-{quote.po_id}").strip().replace("/", "-")

        folder = f"rfqs/{rfq_number}/vendor_quotes/v{quote.supplier_id}"
        key = blob_storage.upload_file(
            file_obj=file_bytes,
            original_filename=file.filename,
            folder=folder
        )
        doc = OrderDocument(
            entity_type="VENDOR_QUOTE",
            entity_id=quote.id,
            po_id=order.id if order else None,
            vendor_quote_id=quote.id,
            doc_type=document_type.upper() if document_type and document_type != "other" else "QUOTATION",
            title=file.filename,
            file_name=file.filename,
            file_path=key,
            file_size=len(file_bytes),
            mime_type=file.content_type,
            created_by=current_user.id
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        return {
            "success": True,
            "id": str(doc.id),
            "file_path": key,
            "file_name": doc.file_name,
            "doc_type": doc.doc_type,
            "vendor_quote_id": quote.id
        }

    # 3. Defect Report Upload
    if defect_report_id:
        def_q = db.query(DefectReport).filter(DefectReport.id == defect_report_id, DefectReport.is_deleted == False)
        def_q = apply_org_filter(def_q, DefectReport, org_context)
        report = def_q.first()
        if not report:
            raise HTTPException(status_code=404, detail="Defect report not found")
        key = blob_storage.upload_file(
            file_obj=file_bytes,
            original_filename=file.filename,
            folder=f"defects/{report.defect_number}"
        )
        img = DefectImage(
            defect_id=report.id,
            file_path=key,
            caption=document_type,
            created_by=current_user.id
        )
        db.add(img)
        db.commit()
        db.refresh(img)
        return {"success": True, "id": str(img.id), "file_path": key}

    # 4. Purchase Order Attachment Upload
    if purchase_order_id:
        po_q = db.query(PurchaseOrder).filter(PurchaseOrder.id == purchase_order_id, PurchaseOrder.is_deleted == False)
        po_q = apply_org_filter(po_q, PurchaseOrder, org_context)
        order = po_q.first()
        if not order:
            raise HTTPException(status_code=404, detail="Purchase order not found")
        folder_po = (order.po_number or f"PO-{order.id}").strip().replace("/", "-")
        key = blob_storage.upload_file(
            file_obj=file_bytes,
            original_filename=file.filename,
            folder=f"orders/{folder_po}/po_documents"
        )
        doc = OrderDocument(
            entity_type="PO",
            entity_id=order.id,
            po_id=order.id,
            doc_type=document_type.upper(),
            title=file.filename,
            file_name=file.filename,
            file_path=key,
            file_size=len(file_bytes),
            mime_type=file.content_type,
            created_by=current_user.id
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        return {"success": True, "id": str(doc.id), "file_path": key}

    # 5. Store Request Attachment Upload
    if request_id:
        from Model.containermgmt.Orders.StoreRequest import StoreRequest
        req_q = db.query(StoreRequest).filter(StoreRequest.id == request_id, StoreRequest.is_deleted == False)
        req = req_q.first()
        folder_name = (req.request_number if req and req.request_number else f"request_{request_id}").strip().replace("/", "-")
        key = blob_storage.upload_file(
            file_obj=file_bytes,
            original_filename=file.filename,
            folder=f"sourcing/requests/{folder_name}/specs"
        )
        doc = OrderDocument(
            entity_type="STORE_REQUEST",
            entity_id=request_id,
            po_id=None,
            doc_type=document_type.upper(),
            title=file.filename,
            file_name=file.filename,
            file_path=key,
            file_size=len(file_bytes),
            mime_type=file.content_type,
            created_by=current_user.id
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        return {"success": True, "id": str(doc.id), "file_path": key}

    # 6. General upload when not linked to a specific entity
    key = blob_storage.upload_file(
        file_obj=file_bytes,
        original_filename=file.filename,
        folder="general"
    )
    doc = OrderDocument(
        entity_type="GENERAL",
        entity_id=None,
        po_id=None,
        doc_type=document_type.upper(),
        title=file.filename,
        file_name=file.filename,
        file_path=key,
        file_size=len(file_bytes),
        mime_type=file.content_type,
        created_by=current_user.id
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return {"success": True, "id": str(doc.id), "file_path": key}

@OrderRouter.get("/documents/{document_id}/download")
async def download_order_document(
    document_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    doc = db.query(OrderDocument).filter(OrderDocument.id == document_id, OrderDocument.is_deleted == False).first()
    if doc and doc.file_path:
        body, ctype, fname = blob_storage.get_file(doc.file_path)
        if body:
            return StreamingResponse(body, media_type=ctype or doc.mime_type or "application/octet-stream", headers={"Content-Disposition": f'attachment; filename="{doc.file_name or fname}"'})
    if document_id.isdigit():
        img = db.query(DefectImage).filter(DefectImage.id == int(document_id), DefectImage.is_deleted == False).first()
        if img and img.file_path:
            body, ctype, fname = blob_storage.get_file(img.file_path)
            if body:
                return StreamingResponse(body, media_type=ctype or "image/jpeg", headers={"Content-Disposition": f'attachment; filename="{fname}"'})
    raise HTTPException(status_code=404, detail="Document file not found")

@OrderRouter.delete("/documents/{document_id}")
async def delete_order_document(
    document_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    doc = db.query(OrderDocument).filter(OrderDocument.id == document_id).first()
    if doc:
        doc.is_deleted = True
        # Clear evidence_doc_id on linked payment if matching
        if doc.payment_id:
            pm = db.query(OrderPayment).filter(OrderPayment.id == doc.payment_id).first()
            if pm and str(pm.evidence_doc_id) == str(doc.id):
                pm.evidence_doc_id = None
        if doc.file_path:
            try:
                blob_storage.delete_file(doc.file_path)
            except Exception as del_err:
                logger.warning("Could not delete blob %s: %s", doc.file_path, del_err)
        db.commit()
        return {"success": True}
    if document_id.isdigit():
        img = db.query(DefectImage).filter(DefectImage.id == int(document_id)).first()
        if img:
            img.is_deleted = True
            if img.file_path:
                try:
                    blob_storage.delete_file(img.file_path)
                except Exception as del_err:
                    logger.warning("Could not delete defect blob %s: %s", img.file_path, del_err)
            db.commit()
            return {"success": True}
    raise HTTPException(status_code=404, detail="Document not found")

@OrderRouter.get("/issues/{issue_id}/pdf")
async def get_issue_pdf_proxy(
    issue_id: int,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    query = (
        db.query(DefectReport)
        .options(
            joinedload(DefectReport.purchase_order),
            joinedload(DefectReport.container),
            joinedload(DefectReport.items),
            joinedload(DefectReport.images)
        )
        .filter(DefectReport.id == issue_id, DefectReport.is_deleted == False)
    )
    query = apply_org_filter(query, DefectReport, org_context)
    d = query.first()
    if not d:
        raise HTTPException(status_code=404, detail="Defect report not found")

    pdf_bytes = generate_defect_report_pdf(d)
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{d.defect_number}.pdf"'}
    )

@OrderRouter.put("/issues/{issue_id}")
async def update_issue_proxy(
    issue_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    query = (
        db.query(DefectReport)
        .options(
            joinedload(DefectReport.purchase_order),
            joinedload(DefectReport.container),
            joinedload(DefectReport.items),
            joinedload(DefectReport.images)
        )
        .filter(DefectReport.id == issue_id, DefectReport.is_deleted == False)
    )
    query = apply_org_filter(query, DefectReport, org_context)
    d = query.first()
    if not d:
        raise HTTPException(status_code=404, detail="Defect report not found")

    if d.status in ["RESOLVED", "CLOSED"]:
        raise HTTPException(
            status_code=400,
            detail="Resolved or closed reports cannot be edited. Reopen the report to modify."
        )

    if "title" in payload:
        d.title = payload["title"].strip() or d.title
    if "description" in payload:
        d.description = payload["description"].strip()
    if "category" in payload:
        d.category = payload["category"]
    if "report_type" in payload:
        d.report_type = payload["report_type"]
    if "po_id" in payload:
        d.po_id = payload["po_id"]
    if "container_id" in payload:
        d.container_id = payload["container_id"]
        if d.container_id:
            cont = db.query(ContainerDetails).filter(ContainerDetails.Container_ID == d.container_id).first()
            if cont and cont.BillOfLanding:
                d.bill_of_lading_no = cont.BillOfLanding
    if "discovery_date" in payload and payload["discovery_date"]:
        try:
            d.discovery_date = datetime.strptime(str(payload["discovery_date"])[:10], "%Y-%m-%d").date()
        except:
            pass

    d.updated_by = current_user.id
    d.updated_at = datetime.utcnow()

    if "items" in payload and isinstance(payload["items"], list):
        for existing in (d.items or []):
            existing.is_deleted = True

        for item in payload["items"]:
            desc_text = item.get("item_description", "").strip()
            if not desc_text: continue
            it_obj = DefectItem(
                defect_id=d.id,
                item_description=desc_text,
                quantity_affected=float(item.get("quantity_affected") or 1.0),
                unit=item.get("unit", "PCS"),
                notes=item.get("notes", "").strip() or None,
                created_by=current_user.id
            )
            db.add(it_obj)

    db.commit()
    db.refresh(d)
    return {"success": True, "id": d.id, "defect_number": d.defect_number, "status": d.status}

@OrderRouter.get("/{order_id}")
def get_order(
    order_id: int,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    is_accounts = is_accounts_user(current_user, org_context)
    can_view_supp = can_user_view_supplier(current_user, org_context)
    query = (
        db.query(PurchaseOrder)
        .options(
            joinedload(PurchaseOrder.order_status_rel),
            joinedload(PurchaseOrder.supplier_rel),
            joinedload(PurchaseOrder.store_request),
            selectinload(PurchaseOrder.items),
            selectinload(PurchaseOrder.child_pos),
            selectinload(PurchaseOrder.shipments).joinedload(OrderShipment.container),
            selectinload(PurchaseOrder.shipments).joinedload(OrderShipment.bill_of_lading),
            selectinload(PurchaseOrder.payments),
            selectinload(PurchaseOrder.documents)
        )
        .filter(PurchaseOrder.id == order_id, PurchaseOrder.is_deleted == False)
    )
    query = apply_org_filter(query, PurchaseOrder, org_context)
    order = query.first()
    if not order:
        raise HTTPException(status_code=404, detail="Purchase order not found")

    order_doc_type = (getattr(order, "doc_type", "PO") or "PO").upper()
    if order_doc_type == "RFQ":
        if not (has_permission(current_user, "View_RFQ") or is_accounts):
            raise HTTPException(status_code=403, detail="Access forbidden: Missing View_RFQ permission")
    else:
        if not (has_permission(current_user, "View_Order") or is_accounts):
            raise HTTPException(status_code=403, detail="Access forbidden: Missing View_Order permission")

    return order_to_dict(order, is_accounts, can_view_supp)

@OrderRouter.post("")
@OrderRouter.post("/")
def create_order(
    payload: dict,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    is_accounts = is_accounts_user(current_user, org_context)
    po_number = payload.get("po_number", "").strip()
    doc_type = (payload.get("doc_type") or ("RFQ" if payload.get("lifecycle_stage") in ["DRAFT", "CONFIRMED", "RFQ_SENT", "QUOTE_RECEIVED"] else "PO")).upper()
    is_rfq = (doc_type == "RFQ")

    if is_rfq:
        if not (has_permission(current_user, "Add_RFQ") or has_permission(current_user, "Add_Order") or is_accounts):
            raise HTTPException(status_code=403, detail="Access forbidden: Missing Add_RFQ permission")
    else:
        if not (has_permission(current_user, "Add_Order") or is_accounts):
            raise HTTPException(status_code=403, detail="Access forbidden: Missing Add_Order permission")

    can_set_financials = is_accounts and (not is_rfq)

    if not po_number:
        # Auto-generate unique sequential number based on doc_type
        year = datetime.utcnow().year
        prefix = f"{doc_type}-{year}-"
        count = db.query(PurchaseOrder).filter(PurchaseOrder.po_number.like(f"{prefix}%")).count()
        po_number = f"{prefix}{count + 1:04d}"

    existing = db.query(PurchaseOrder).filter(
        PurchaseOrder.po_number.ilike(po_number),
        PurchaseOrder.is_deleted == False
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Order with PO Number '{po_number}' already exists")

    # Match status
    status_val = payload.get("status", "DRAFT")
    status_id = payload.get("status_id")
    status_obj = None
    if status_id:
        status_obj = db.query(OrderStatus).filter(OrderStatus.id == status_id, OrderStatus.is_deleted == False).first()
    if not status_obj and status_val:
        status_obj = db.query(OrderStatus).filter(
            or_(OrderStatus.code == status_val, OrderStatus.name == status_val),
            OrderStatus.is_deleted == False
        ).first()

    status_label = status_obj.name if status_obj else (payload.get("status_label") or status_val)

    # Supplier info
    supplier_id = payload.get("supplier")
    company = payload.get("company", "").strip()
    if supplier_id:
        supp = db.query(Supplier).filter(Supplier.supplier_id == supplier_id).first()
        if supp:
            company = supp.name

    target_org_id = payload.get("org_id")
    if not target_org_id:
        consignee_val = (payload.get("consignee") or "").upper()
        sheet_val = (payload.get("sheet_type") or "").upper()
        if "NOBLE" in consignee_val or "NOBLE" in sheet_val:
            target_org_id = 2
        elif "SAHAJANAND" in consignee_val or "SAHAJANAND" in sheet_val:
            target_org_id = 3
        elif "SAHAJ" in consignee_val or "SAHAJ" in sheet_val:
            target_org_id = 1
        else:
            target_org_id = org_context.selected_org_id or current_user.org_id or 1

    if not org_context.is_root and target_org_id not in org_context.allowed_org_ids:
        target_org_id = current_user.org_id

    # Helpers
    def parse_d(val):
        if not val: return None
        try: return datetime.strptime(str(val)[:10], "%Y-%m-%d").date()
        except: return None

    def parse_numeric(val):
        if val is None or val == "": return None
        try: return float(val)
        except: return None

    new_order = PurchaseOrder(
        po_number=po_number,
        po_nce=payload.get("po_nce", "").strip() or None if can_set_financials else None,
        doc_type=doc_type,
        parent_rfq_id=payload.get("parent_rfq_id"),
        origin_rfq_number=payload.get("origin_rfq_number"),
        split_index=payload.get("split_index"),
        request_id=payload.get("request_id"),
        supplier_id=supplier_id or None,
        company=company or None,
        goods_description=payload.get("goods_description", "").strip() or None,
        material_ids=payload.get("material_ids") or [],
        
        status_id=status_obj.id if status_obj else None,
        status=status_obj.code if status_obj else status_val,
        status_label=status_label,

        lifecycle_stage=payload.get("lifecycle_stage") or "DRAFT",
        lifecycle_version=int(payload.get("lifecycle_version") or 1),
        stage_version=1,
        lifecycle_locked=bool(payload.get("lifecycle_locked", False)),
        selected_quote_id=payload.get("selected_quote_id") if can_set_financials else None,
        
        payment_status=payload.get("payment_status", "NONE"),
        production_status=payload.get("production_status", "NOT_STARTED"),
        shipment_status=payload.get("shipment_status", "NOT_SHIPPED"),
        receipt_status=payload.get("receipt_status", "PENDING"),

        total_amount=parse_numeric(payload.get("total_amount")) if can_set_financials else None,
        advance_amount=parse_numeric(payload.get("advance_amount")) if can_set_financials else None,
        balance_amount=parse_numeric(payload.get("balance_amount")) if can_set_financials else None,
        currency=payload.get("currency", "USD"),

        sheet_type=payload.get("sheet_type", "NOBLE"),
        consignee=payload.get("consignee", "").strip() or None,
        year=payload.get("year") or datetime.utcnow().year,
        urgent_action=bool(payload.get("urgent_action", False)),
        
        order_mail_date=parse_d(payload.get("order_mail_date")) or datetime.utcnow().date(),
        quote_sent_date=parse_d(payload.get("quote_sent_date")) or (datetime.utcnow().date() if (payload.get("lifecycle_stage") or payload.get("status") or "DRAFT").upper() in ["RFQ_SENT", "SOURCING", "QUOTE_RECEIVED", "QUOTE_APPROVED", "PO_ISSUED", "ORDERED"] else None),
        quote_received_date=parse_d(payload.get("quote_received_date")) or (datetime.utcnow().date() if (payload.get("lifecycle_stage") or payload.get("status") or "DRAFT").upper() in ["QUOTE_RECEIVED", "QUOTE_APPROVED", "PO_ISSUED", "ORDERED"] else None),
        pi_confirmed_date=parse_d(payload.get("pi_confirmed_date")) or (datetime.utcnow().date() if (payload.get("lifecycle_stage") or payload.get("status") or "DRAFT").upper() in ["QUOTE_APPROVED", "PO_ISSUED", "ORDERED"] else None),
        payment_date=parse_d(payload.get("payment_date")) if can_set_financials else None,
        balance_payment_date=parse_d(payload.get("balance_payment_date")) if can_set_financials else None,
        eta_date=parse_d(payload.get("eta_date")),
        freight_type=payload.get("freight_type", "Sea Freight"),
        remark=payload.get("remark", "").strip() or None,
        org_id=target_org_id,
        created_by=current_user.id
    )
    db.add(new_order)
    db.flush()

    # Add line items if provided
    for it in payload.get("items", []):
        desc_text = it.get("description", "").strip()
        if not desc_text: continue
        u_price = parse_numeric(it.get("unit_price")) if can_set_financials else None
        tot_price = parse_numeric(it.get("total_price")) if can_set_financials else None
        qty = float(it.get("quantity_ordered") or 1.0)
        if u_price is not None and tot_price is None:
            tot_price = qty * u_price
        po_it = POItem(
            po_id=new_order.id,
            request_item_id=it.get("request_item_id"),
            product_id=it.get("product_id"),
            item_code=it.get("item_code", "").strip() or None,
            description=desc_text,
            quantity_ordered=qty,
            unit=it.get("unit", "PCS"),
            unit_price=u_price,
            draft_unit_price=u_price,
            total_price=tot_price,
            notes=it.get("notes", "").strip() or None,
            created_by=current_user.id
        )
        db.add(po_it)

    # If linked to a store request, update request status to ORDERED
    if new_order.request_id:
        req_obj = db.query(StoreRequest).filter(StoreRequest.id == new_order.request_id).first()
        if req_obj:
            req_obj.status = "ORDERED"
            req_obj.status_label = "Ordered"

    # Status history log
    hist = OrderStatusHistory(
        entity_type="PO",
        entity_id=new_order.id,
        po_id=new_order.id,
        org_id=new_order.org_id,
        from_status=None,
        to_status=new_order.status,
        to_status_label=new_order.status_label,
        changed_by=current_user.id,
        notes="PO Created"
    )
    db.add(hist)
    db.flush()

    # Capture initial version snapshot
    from .LifecycleService import LifecycleService
    LifecycleService.capture_po_snapshot(
        po=new_order,
        db=db,
        transition_type="INITIAL",
        change_summary=f"Created PO in {new_order.lifecycle_stage} v1",
        diff_data={"initial_items_count": len(new_order.items or [])},
        user_id=current_user.id
    )

    db.commit()
    db.refresh(new_order)
    sync_order_document(new_order)
    logger.info("Created PO %s by %s", new_order.po_number, current_user.username)
    can_view_supp = can_user_view_supplier(current_user, org_context)
    return order_to_dict(new_order, is_accounts, can_view_supp)

@OrderRouter.put("/{order_id}")
def update_order(
    order_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    is_accounts = is_accounts_user(current_user, org_context)
    query = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id, PurchaseOrder.is_deleted == False)
    query = apply_org_filter(query, PurchaseOrder, org_context)
    order = query.first()
    if not order:
        raise HTTPException(status_code=404, detail="Purchase order not found")

    order_doc_type = (getattr(order, "doc_type", "PO") or "PO").upper()
    if order_doc_type == "RFQ":
        if not (has_permission(current_user, "Edit_RFQ") or has_permission(current_user, "Edit_Order") or is_accounts):
            raise HTTPException(status_code=403, detail="Access forbidden: Missing Edit_RFQ permission")
    else:
        if not (has_permission(current_user, "Edit_Order") or is_accounts):
            raise HTTPException(status_code=403, detail="Access forbidden: Missing Edit_Order permission")

    def parse_d(val):
        if not val: return None
        try: return datetime.strptime(str(val)[:10], "%Y-%m-%d").date()
        except: return None

    def parse_numeric(val):
        if val is None or val == "": return None
        try: return float(val)
        except: return None

    old_status = order.status
    old_supplier = order.supplier_id
    old_company = order.company
    old_sheet_type = order.sheet_type
    old_consignee = order.consignee
    old_freight_type = order.freight_type
    old_total_amount = float(order.total_amount) if order.total_amount is not None else None

    diff_items_mod = []
    diff_items_add = []
    diff_items_rem = []
    header_changes = {}

    if "po_number" in payload:
        po_num = (payload.get("po_number") or "").strip()
        if po_num:
            existing = db.query(PurchaseOrder).filter(
                PurchaseOrder.po_number.ilike(po_num),
                PurchaseOrder.id != order_id,
                PurchaseOrder.is_deleted == False
            ).first()
            if existing:
                raise HTTPException(status_code=400, detail=f"Order with PO Number '{po_num}' already exists")
            order.po_number = po_num

    if "po_nce" in payload and is_accounts:
        order.po_nce = (payload.get("po_nce") or "").strip() or None
    if "supplier" in payload and is_accounts:
        order.supplier_id = payload["supplier"] or None
        if order.supplier_id:
            supp = db.query(Supplier).filter(Supplier.supplier_id == order.supplier_id).first()
            if supp:
                order.company = supp.name
    if "company" in payload and is_accounts and not order.supplier_id:
        order.company = (payload.get("company") or "").strip() or None
    if "goods_description" in payload:
        order.goods_description = (payload.get("goods_description") or "").strip() or None
    if "doc_type" in payload:
        order.doc_type = payload["doc_type"].upper()
    if "parent_rfq_id" in payload:
        order.parent_rfq_id = payload["parent_rfq_id"]
    if "origin_rfq_number" in payload:
        order.origin_rfq_number = payload["origin_rfq_number"]
    if "split_index" in payload:
        order.split_index = payload["split_index"]
    if "lifecycle_stage" in payload and payload["lifecycle_stage"]:
        order.lifecycle_stage = payload["lifecycle_stage"]
    elif "status" in payload and not order.lifecycle_stage:
        order.lifecycle_stage = payload["status"]

    # Status update
    if "status" in payload or "status_id" in payload:
        s_val = payload.get("status")
        s_id = payload.get("status_id")

        # Financial status decoupling guard:
        if s_val and str(s_val).upper() in ["PART_PAID", "PAID"]:
            order.payment_status = "FULLY_PAID" if str(s_val).upper() == "PAID" else "PART_PAID"
            s_val = None
            s_id = None

        st_obj = None
        if s_id:
            st_obj = db.query(OrderStatus).filter(OrderStatus.id == s_id, OrderStatus.is_deleted == False).first()
        if not st_obj and s_val:
            st_obj = db.query(OrderStatus).filter(
                or_(OrderStatus.code == s_val, OrderStatus.name == s_val),
                OrderStatus.is_deleted == False
            ).first()
        if st_obj:
            order.status_id = st_obj.id
            order.status = st_obj.code
            order.status_label = st_obj.name
        elif s_val:
            order.status = s_val
            order.status_label = payload.get("status_label", s_val)

        # Log transition if changed
        if order.status != old_status:
            hist = OrderStatusHistory(
                entity_type="PO",
                entity_id=order.id,
                po_id=order.id,
                org_id=order.org_id,
                from_status=old_status,
                to_status=order.status,
                to_status_label=order.status_label,
                changed_by=current_user.id,
                notes=payload.get("status_note", "Status updated")
            )
            db.add(hist)

            today_date = datetime.utcnow().date()
            effective_stage = (order.lifecycle_stage or order.status or "").upper()
            if effective_stage in ["CONFIRMED", "RFQ_SENT", "SOURCING", "QUOTE_RECEIVED", "QUOTE_APPROVED", "PO_ISSUED", "ORDERED"]:
                if not order.order_mail_date:
                    order.order_mail_date = today_date
            if effective_stage in ["RFQ_SENT", "SOURCING", "QUOTE_RECEIVED", "QUOTE_APPROVED", "PO_ISSUED", "ORDERED"]:
                if not order.quote_sent_date:
                    order.quote_sent_date = today_date
            if effective_stage in ["QUOTE_RECEIVED", "QUOTE_APPROVED", "PO_ISSUED", "ORDERED"]:
                if not order.quote_received_date:
                    order.quote_received_date = today_date
            if effective_stage in ["QUOTE_APPROVED", "PO_ISSUED", "ORDERED"]:
                if not order.pi_confirmed_date:
                    order.pi_confirmed_date = today_date
            if effective_stage in ["PART_PAID", "PAID", "ADVANCE_PAID"]:
                if not order.payment_date:
                    order.payment_date = today_date
            if effective_stage in ["PAID", "FULLY_PAID"]:
                if not order.balance_payment_date:
                    order.balance_payment_date = today_date
            # Note: eta_date is not auto-updated here; shipping schedule is determined manually or via BL/vessel tracking

    is_rfq = ((order.doc_type or "").upper() == "RFQ")
    can_set_financials = is_accounts and (not is_rfq)

    if is_rfq:
        order.total_amount = None
        order.advance_amount = None
        order.balance_amount = None
        order.payment_date = None
        order.balance_payment_date = None
    elif can_set_financials:
        if "total_amount" in payload: order.total_amount = parse_numeric(payload["total_amount"])
        if "advance_amount" in payload: order.advance_amount = parse_numeric(payload["advance_amount"])
        if "balance_amount" in payload: order.balance_amount = parse_numeric(payload["balance_amount"])
        if "currency" in payload: order.currency = payload["currency"]
        if "payment_date" in payload: order.payment_date = parse_d(payload["payment_date"])
        if "balance_payment_date" in payload: order.balance_payment_date = parse_d(payload["balance_payment_date"])

    if "payment_status" in payload: order.payment_status = payload["payment_status"]
    if "production_status" in payload: order.production_status = payload["production_status"]
    if "shipment_status" in payload: order.shipment_status = payload["shipment_status"]
    if "receipt_status" in payload: order.receipt_status = payload["receipt_status"]

    if "order_mail_date" in payload: order.order_mail_date = parse_d(payload["order_mail_date"])
    if "quote_sent_date" in payload: order.quote_sent_date = parse_d(payload["quote_sent_date"])
    if "quote_received_date" in payload: order.quote_received_date = parse_d(payload["quote_received_date"])
    if "pi_confirmed_date" in payload: order.pi_confirmed_date = parse_d(payload["pi_confirmed_date"])
    if "eta_date" in payload: order.eta_date = parse_d(payload["eta_date"])
    if "freight_type" in payload: order.freight_type = payload["freight_type"]
    if "remark" in payload: order.remark = (payload.get("remark") or "").strip() or None
    if "urgent_action" in payload: order.urgent_action = bool(payload["urgent_action"])

    if "supplier" in payload and order.supplier_id != old_supplier:
        header_changes["supplier"] = {"old": old_supplier, "new": order.supplier_id}
    elif "company" in payload and order.company != old_company:
        header_changes["company"] = {"old": old_company, "new": order.company}
    if "sheet_type" in payload and order.sheet_type != old_sheet_type:
        header_changes["sheet_type"] = {"old": old_sheet_type, "new": order.sheet_type}
    if "consignee" in payload and order.consignee != old_consignee:
        header_changes["consignee"] = {"old": old_consignee, "new": order.consignee}
    if "freight_type" in payload and order.freight_type != old_freight_type:
        header_changes["freight_type"] = {"old": old_freight_type, "new": order.freight_type}
    if "total_amount" in payload and (float(order.total_amount) if order.total_amount is not None else None) != old_total_amount:
        header_changes["total_amount"] = {"old": old_total_amount, "new": float(order.total_amount) if order.total_amount is not None else None}

    if "org_id" in payload and org_context.is_root:
        order.org_id = payload["org_id"]
    elif org_context.is_root and ("consignee" in payload or "sheet_type" in payload):
        consignee_val = (payload.get("consignee") or order.consignee or "").upper()
        sheet_val = (payload.get("sheet_type") or order.sheet_type or "").upper()
        if "NOBLE" in consignee_val or "NOBLE" in sheet_val:
            order.org_id = 2
        elif "SAHAJANAND" in consignee_val or "SAHAJANAND" in sheet_val:
            order.org_id = 3
        elif "SAHAJ" in consignee_val or "SAHAJ" in sheet_val:
            order.org_id = 1

    # ── Line items update & audit delta tracking ──────────────────────────────
    items_mutated = False
    if "items" in payload:
        from .LifecycleService import LifecycleService
        incoming_items = payload["items"]
        revision_reason = (payload.get("revision_reason") or "").strip() or None
        warning_level = LifecycleService.get_warning_level(order.lifecycle_stage or "DRAFT")
        
        existing_items_map = {it.id: it for it in (order.items or []) if not it.is_deleted}
        seen_ids = set()
        
        for item_data in incoming_items:
            it_id = item_data.get("id")
            desc_text = (item_data.get("description") or "").strip()
            if not desc_text:
                continue
            
            qty = parse_numeric(item_data.get("quantity_ordered")) or 1.0
            u_price = parse_numeric(item_data.get("unit_price")) if can_set_financials else None
            tot_price = parse_numeric(item_data.get("total_price")) if can_set_financials else None
            if u_price is not None and tot_price is None:
                tot_price = qty * u_price

            if it_id and it_id in existing_items_map:
                existing_item = existing_items_map[it_id]
                seen_ids.add(it_id)
                old_qty = float(existing_item.quantity_ordered or 0)
                old_price = float(existing_item.unit_price) if existing_item.unit_price is not None else None
                
                changed = (abs(old_qty - qty) > 0.001) or (can_set_financials and old_price != u_price) or (existing_item.description != desc_text)
                if changed:
                    items_mutated = True
                    diff_items_mod.append({
                        "item_id": existing_item.id,
                        "description": desc_text,
                        "old_qty": old_qty,
                        "new_qty": qty,
                        "old_unit_price": old_price,
                        "new_unit_price": u_price
                    })
                    existing_item.description = desc_text
                    existing_item.quantity_ordered = qty
                    if is_rfq:
                        existing_item.unit_price = None
                        existing_item.total_price = None
                        existing_item.draft_unit_price = None
                        existing_item.approved_unit_price = None
                        existing_item.po_unit_price = None
                        existing_item.proforma_unit_price = None
                    elif can_set_financials:
                        existing_item.unit_price = u_price
                        existing_item.total_price = tot_price
                    existing_item.item_code = (item_data.get("item_code") or "").strip() or None
                    existing_item.unit = item_data.get("unit", "PCS")
                    existing_item.product_id = item_data.get("product_id")
                    existing_item.notes = (item_data.get("notes") or "").strip() or None
                    existing_item.updated_by = current_user.id
                    
                    if warning_level in ["WARNING", "CRITICAL"]:
                        LifecycleService.record_item_history(
                            po=order,
                            item=existing_item,
                            action="UPDATE",
                            field_name="ALL",
                            old_value=str(old_price),
                            new_value=str(u_price),
                            reason=revision_reason,
                            user_id=current_user.id,
                            db=db
                        )
            else:
                items_mutated = True
                diff_items_add.append({
                    "description": desc_text,
                    "quantity": qty,
                    "unit_price": u_price,
                    "unit": item_data.get("unit", "PCS")
                })
                new_item = POItem(
                    po_id=order.id,
                    request_item_id=item_data.get("request_item_id"),
                    product_id=item_data.get("product_id"),
                    item_code=(item_data.get("item_code") or "").strip() or None,
                    description=desc_text,
                    quantity_ordered=qty,
                    unit=item_data.get("unit", "PCS"),
                    unit_price=u_price,
                    total_price=tot_price,
                    draft_unit_price=u_price,
                    item_status="ACTIVE",
                    notes=(item_data.get("notes") or "").strip() or None,
                    created_by=current_user.id
                )
                db.add(new_item)
                db.flush()
                if warning_level in ["WARNING", "CRITICAL"]:
                    LifecycleService.record_item_history(
                        po=order,
                        item=new_item,
                        action="CREATE",
                        field_name="ALL",
                        old_value=None,
                        new_value=str(u_price),
                        reason=revision_reason,
                        user_id=current_user.id,
                        db=db
                    )

        # Removed items
        for old_id, old_item in existing_items_map.items():
            if old_id not in seen_ids:
                items_mutated = True
                diff_items_rem.append({
                    "item_id": old_id,
                    "description": old_item.description,
                    "quantity": float(old_item.quantity_ordered or 0),
                    "unit_price": float(old_item.unit_price) if old_item.unit_price is not None else None
                })
                old_item.is_deleted = True
                old_item.item_status = "USER_REMOVED"
                old_item.removed_at_stage = order.lifecycle_stage
                old_item.deleted_by = current_user.id
                if warning_level in ["WARNING", "CRITICAL"]:
                    LifecycleService.record_item_history(
                        po=order,
                        item=old_item,
                        action="REMOVE",
                        field_name="item_status",
                        old_value="ACTIVE",
                        new_value="USER_REMOVED",
                        reason=revision_reason,
                        user_id=current_user.id,
                        db=db
                    )

    # Stage versioning and version snapshot capture
    if items_mutated or header_changes:
        order.stage_version = (getattr(order, "stage_version", 1) or 1) + 1
        order.lifecycle_version = (order.lifecycle_version or 1) + 1

        parts = []
        if diff_items_mod:
            parts.append(f"{len(diff_items_mod)} item(s) modified")
        if diff_items_add:
            parts.append(f"{len(diff_items_add)} item(s) added")
        if diff_items_rem:
            parts.append(f"{len(diff_items_rem)} item(s) removed")
        if header_changes:
            parts.append(f"Header fields changed ({', '.join(header_changes.keys())})")

        change_desc = (payload.get("revision_reason") or "").strip()
        if not change_desc:
            change_desc = "; ".join(parts) or "PO Updated"

        db.flush()
        from .LifecycleService import LifecycleService
        LifecycleService.capture_po_snapshot(
            po=order,
            db=db,
            transition_type="MUTATION",
            change_summary=change_desc,
            diff_data={
                "items_modified": diff_items_mod,
                "items_added": diff_items_add,
                "items_removed": diff_items_rem,
                "header_changes": header_changes,
                "revision_reason": (payload.get("revision_reason") or "").strip() or None
            },
            user_id=current_user.id
        )

    # Ensure active payments in OrderPayment ledger are preserved in order advance_amount and balance_amount
    active_payments = db.query(OrderPayment).filter(
        OrderPayment.po_id == order.id,
        OrderPayment.is_deleted == False
    ).all()
    if active_payments:
        total_paid = sum(float(p.amount or 0) for p in active_payments)
        order.advance_amount = total_paid
        total_order = float(order.total_amount or 0)
        order.balance_amount = max(0.0, total_order - total_paid)

    order.updated_by = current_user.id
    db.commit()
    db.refresh(order)
    sync_order_document(order)
    can_view_supp = can_user_view_supplier(current_user, org_context)
    return order_to_dict(order, is_accounts, can_view_supp)

@OrderRouter.patch("/{order_id}/status")
async def update_order_status_patch(
    order_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    query = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id, PurchaseOrder.is_deleted == False)
    query = apply_org_filter(query, PurchaseOrder, org_context)
    order = query.first()
    if not order:
        raise HTTPException(status_code=404, detail="Purchase order not found")

    new_status = payload.get("status")
    if not new_status:
        raise HTTPException(status_code=400, detail="Missing status")

    # Financial status decoupling guard:
    if str(new_status).upper() in ["PART_PAID", "PAID"]:
        order.payment_status = "FULLY_PAID" if str(new_status).upper() == "PAID" else "PART_PAID"
        if not order.payment_date and str(new_status).upper() in ["PART_PAID", "PAID"]:
            order.payment_date = datetime.utcnow().date()
        if not order.balance_payment_date and str(new_status).upper() == "PAID":
            order.balance_payment_date = datetime.utcnow().date()
        order.updated_by = current_user.id
        db.commit()
        db.refresh(order)
        sync_order_document(order)
        is_accounts = is_accounts_user(current_user, org_context)
        can_view_supp = can_user_view_supplier(current_user, org_context)
        return order_to_dict(order, is_accounts, can_view_supp)

    old_status = order.status
    st_obj = db.query(OrderStatus).filter(
        or_(OrderStatus.code == new_status, OrderStatus.name == new_status),
        OrderStatus.is_deleted == False
    ).first()
    if st_obj:
        order.status_id = st_obj.id
        order.status = st_obj.code
        order.status_label = st_obj.name
    else:
        order.status = new_status
        order.status_label = new_status

    # Synchronize lifecycle_stage if provided or if new_status maps to lifecycle stages
    target_lifecycle = payload.get("lifecycle_stage") or new_status
    if target_lifecycle:
        canonical_stage = str(target_lifecycle).upper()
        if canonical_stage in [
            "DRAFT", "CONFIRMED", "RFQ_SENT", "SOURCING",
            "QUOTE_RECEIVED", "QUOTE_APPROVED", "PO_ISSUED", "PROFORMA", "ORDERED"
        ]:
            order.lifecycle_stage = canonical_stage

    if order.status != old_status:
        hist = OrderStatusHistory(
            entity_type="PO",
            entity_id=order.id,
            po_id=order.id,
            org_id=order.org_id,
            from_status=old_status,
            to_status=order.status,
            to_status_label=order.status_label,
            changed_by=current_user.id,
            notes=payload.get("status_note", "Quick status change")
        )
        db.add(hist)

        today_date = datetime.utcnow().date()
        effective_stage = (order.lifecycle_stage or order.status or "").upper()
        if effective_stage in ["CONFIRMED", "RFQ_SENT", "SOURCING", "QUOTE_RECEIVED", "QUOTE_APPROVED", "PO_ISSUED", "ORDERED"]:
            if not order.order_mail_date:
                order.order_mail_date = today_date
        if effective_stage in ["RFQ_SENT", "SOURCING", "QUOTE_RECEIVED", "QUOTE_APPROVED", "PO_ISSUED", "ORDERED"]:
            if not order.quote_sent_date:
                order.quote_sent_date = today_date
        if effective_stage in ["QUOTE_RECEIVED", "QUOTE_APPROVED", "PO_ISSUED", "ORDERED"]:
            if not order.quote_received_date:
                order.quote_received_date = today_date
        if effective_stage in ["QUOTE_APPROVED", "PO_ISSUED", "ORDERED"]:
            if not order.pi_confirmed_date:
                order.pi_confirmed_date = today_date
        if effective_stage in ["PART_PAID", "PAID", "ADVANCE_PAID"]:
            if not order.payment_date:
                order.payment_date = today_date
        if effective_stage in ["PAID", "FULLY_PAID"]:
            if not order.balance_payment_date:
                order.balance_payment_date = today_date
        # Note: eta_date is not auto-updated here; shipping schedule is determined manually or via BL/vessel tracking

    order.updated_by = current_user.id
    db.commit()
    db.refresh(order)
    sync_order_document(order)
    is_accounts = is_accounts_user(current_user, org_context)
    can_view_supp = can_user_view_supplier(current_user, org_context)
    return order_to_dict(order, is_accounts, can_view_supp)

# ── Link Shipments (PO ↔ BL / Container) ──────────────────────────────────────
@OrderRouter.post("/{order_id}/shipments")
async def link_shipment(
    order_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    query = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id, PurchaseOrder.is_deleted == False)
    query = apply_org_filter(query, PurchaseOrder, org_context)
    order = query.first()
    if not order:
        raise HTTPException(status_code=404, detail="Purchase order not found")

    bl_no = payload.get("bill_of_lading_no", "").strip()
    if not bl_no:
        raise HTTPException(status_code=422, detail="Bill of Lading number is required")

    container_id = payload.get("container_id")

    shipment = OrderShipment(
        po_id=order.id,
        bill_of_lading_no=bl_no,
        container_id=container_id,
        shipment_status=payload.get("shipment_status", "IN_TRANSIT"),
        notes=payload.get("notes", "").strip() or None,
        created_by=current_user.id
    )
    db.add(shipment)

    # Update PO shipment status automatically
    order.shipment_status = "SHIPPED"
    shipped_st = db.query(OrderStatus).filter(OrderStatus.code == "SHIPPED").first()
    if shipped_st:
        order.status_id = shipped_st.id
        order.status = "SHIPPED"
        order.status_label = "Shipped"

    db.commit()
    return {"success": True, "message": f"Linked BL {bl_no} to PO {order.po_number}"}

# ── Get Order Payments Ledger ────────────────────────────────────────────────
@OrderRouter.get("/{order_id}/payments")
@OrderRouter.get("/{order_id}/payments/")
async def get_order_payments(
    order_id: int,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    if not is_accounts_user(current_user, org_context):
        raise HTTPException(status_code=403, detail="Only Accounts/Finance users can view payments.")

    query = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id, PurchaseOrder.is_deleted == False)
    query = apply_org_filter(query, PurchaseOrder, org_context)
    order = query.first()
    if not order:
        raise HTTPException(status_code=404, detail="Purchase order not found")

    payments = db.query(OrderPayment).options(
        joinedload(OrderPayment.evidence_doc),
        selectinload(OrderPayment.documents)
    ).filter(
        OrderPayment.po_id == order.id,
        OrderPayment.is_deleted == False
    ).order_by(OrderPayment.id.desc()).all()

    return {
        "success": True,
        "payments": [
            {
                "id": pm.id,
                "payment_type": pm.payment_type,
                "amount": float(pm.amount or 0),
                "currency": pm.currency,
                "paid_date": pm.paid_date.isoformat() if pm.paid_date else None,
                "payment_method": pm.payment_method,
                "reference_number": pm.reference_number,
                "notes": pm.notes,
                "status": pm.status,
                "created_at": pm.created_at.isoformat() if hasattr(pm, 'created_at') and pm.created_at else None,
                "evidence_doc_id": str(pm.evidence_doc_id) if pm.evidence_doc_id else None,
                "evidence_doc": {
                    "id": str(pm.evidence_doc.id),
                    "file_name": pm.evidence_doc.file_name,
                    "title": pm.evidence_doc.title,
                    "file_path": pm.evidence_doc.file_path,
                    "file_size": pm.evidence_doc.file_size,
                    "mime_type": pm.evidence_doc.mime_type,
                } if pm.evidence_doc and not pm.evidence_doc.is_deleted else None,
                "documents": [
                    {
                        "id": str(d.id),
                        "file_name": d.file_name,
                        "title": d.title,
                        "file_path": d.file_path,
                        "file_size": d.file_size,
                        "mime_type": d.mime_type,
                        "created_at": d.created_at.isoformat() if d.created_at else None,
                    }
                    for d in (pm.documents or []) if not d.is_deleted
                ]
            }
            for pm in payments
        ],
        "advance_amount": float(order.advance_amount or 0),
        "balance_amount": float(order.balance_amount or 0),
        "payment_status": order.payment_status
    }

# ── Record Payments ───────────────────────────────────────────────────────────
@OrderRouter.post("/{order_id}/payments")
@OrderRouter.post("/{order_id}/payments/")
async def record_payment(
    order_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    if not is_accounts_user(current_user, org_context):
        raise HTTPException(status_code=403, detail="Only Accounts/Finance users can record payments.")

    query = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id, PurchaseOrder.is_deleted == False)
    query = apply_org_filter(query, PurchaseOrder, org_context)
    order = query.first()
    if not order:
        raise HTTPException(status_code=404, detail="Purchase order not found")

    if (order.doc_type or "").upper() == "RFQ":
        raise HTTPException(
            status_code=400,
            detail="Cannot record payments on an RFQ document. Payments are only permitted on awarded Purchase Orders (PO)."
        )

    raw_amt = float(payload.get("amount") or 0)
    p_type = (payload.get("payment_type") or "ADVANCE").strip().upper()

    # Negative amount validation:
    # Negative amount indicates a Return Payment (Refund) and is ONLY acceptable when payment type is RETURN
    if p_type == "RETURN":
        if raw_amt == 0:
            raise HTTPException(status_code=400, detail="Return payment amount cannot be zero.")
        amt = -abs(raw_amt)
    else:
        if raw_amt < 0:
            raise HTTPException(
                status_code=400,
                detail="Negative amounts are only acceptable when payment type is 'Return Payment'."
            )
        if raw_amt <= 0:
            raise HTTPException(status_code=400, detail="Payment amount must be greater than zero.")
        amt = raw_amt

    # Check overpayment & refund limits
    allow_overpayment = bool(payload.get("allow_overpayment", False))

    current_active_payments = db.query(OrderPayment).filter(
        OrderPayment.po_id == order.id,
        OrderPayment.is_deleted == False
    ).all()
    current_paid = sum(float(p.amount or 0) for p in current_active_payments)

    total_order = float(order.total_amount or 0)
    if total_order <= 0:
        items_total = sum(float(it.total_price or 0) for it in (order.items or []) if not getattr(it, 'is_deleted', False))
        if items_total > 0:
            total_order = items_total
            order.total_amount = items_total

    remaining_due = max(0.0, total_order - current_paid)

    if p_type == "RETURN":
        if abs(amt) > (current_paid + 0.01):
            raise HTTPException(
                status_code=400,
                detail=f"Return payment ({abs(amt):.2f}) cannot exceed the total amount already paid ({current_paid:.2f})."
            )
    else:
        if total_order > 0 and amt > (remaining_due + 0.01):
            if not allow_overpayment:
                raise HTTPException(
                    status_code=400,
                    detail=f"Payment amount ({amt:.2f}) exceeds the remaining order due ({remaining_due:.2f}). Overpayment is restricted without explicit authorization."
                )

    paid_d = None
    if payload.get("paid_date"):
        try:
            paid_d = datetime.strptime(payload["paid_date"][:10], "%Y-%m-%d").date()
        except Exception:
            paid_d = date.today()

    payment = OrderPayment(
        po_id=order.id,
        payment_type=p_type,
        amount=amt,
        currency=payload.get("currency", order.currency or "USD"),
        paid_date=paid_d,
        status="RETURNED" if p_type == "RETURN" else "PAID",
        payment_method=payload.get("payment_method"),
        reference_number=payload.get("reference_number"),
        notes=payload.get("notes"),
        created_by=current_user.id
    )
    db.add(payment)
    db.flush()

    # Recalculate accumulated active payments
    active_payments = db.query(OrderPayment).filter(
        OrderPayment.po_id == order.id,
        OrderPayment.is_deleted == False
    ).order_by(OrderPayment.id.desc()).all()
    total_paid = sum(float(p.amount or 0) for p in active_payments)
    total_order = float(order.total_amount or 0)

    order.advance_amount = total_paid
    order.balance_amount = max(0.0, total_order - total_paid)

    # Auto-fill payment milestone dates
    if p_type == "ADVANCE" and not order.payment_date and payment.paid_date:
        order.payment_date = payment.paid_date
    elif p_type in ["BALANCE", "FINAL"] and not order.balance_payment_date and payment.paid_date:
        order.balance_payment_date = payment.paid_date
    elif order.payment_status == "FULLY_PAID" and not order.balance_payment_date and payment.paid_date:
        order.balance_payment_date = payment.paid_date

    # Automatic payment status update based on totals and payment type
    if total_order > 0 and total_paid >= (total_order - 0.01):
        order.payment_status = "FULLY_PAID"
    elif total_paid > 0:
        order.payment_status = "PART_PAID"
    else:
        order.payment_status = "NONE"

    db.commit()
    db.refresh(payment)

    return {
        "success": True,
        "message": f"Payment entry of {amt} recorded for PO {order.po_number}",
        "payment": {
            "id": payment.id,
            "payment_type": payment.payment_type,
            "amount": float(payment.amount or 0),
            "currency": payment.currency,
            "paid_date": payment.paid_date.isoformat() if payment.paid_date else None,
            "payment_method": payment.payment_method,
            "reference_number": payment.reference_number,
            "notes": payment.notes,
            "status": payment.status,
            "created_at": payment.created_at.isoformat() if hasattr(payment, 'created_at') and payment.created_at else None,
        },
        "advance_amount": float(order.advance_amount or 0),
        "balance_amount": float(order.balance_amount or 0),
        "payment_status": order.payment_status,
        "payments": [
            {
                "id": pm.id,
                "payment_type": pm.payment_type,
                "amount": float(pm.amount or 0),
                "currency": pm.currency,
                "paid_date": pm.paid_date.isoformat() if pm.paid_date else None,
                "payment_method": pm.payment_method,
                "reference_number": pm.reference_number,
                "notes": pm.notes,
                "status": pm.status,
                "created_at": pm.created_at.isoformat() if hasattr(pm, 'created_at') and pm.created_at else None,
            }
            for pm in active_payments
        ]
    }

# ── Update Payment ────────────────────────────────────────────────────────────
@OrderRouter.put("/{order_id}/payments/{payment_id}")
@OrderRouter.put("/{order_id}/payments/{payment_id}/")
async def update_payment(
    order_id: int,
    payment_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    if not is_accounts_user(current_user, org_context):
        raise HTTPException(status_code=403, detail="Only Accounts/Finance users can update payments.")

    query = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id, PurchaseOrder.is_deleted == False)
    query = apply_org_filter(query, PurchaseOrder, org_context)
    order = query.first()
    if not order:
        raise HTTPException(status_code=404, detail="Purchase order not found")

    payment = db.query(OrderPayment).filter(
        OrderPayment.id == payment_id,
        OrderPayment.po_id == order.id,
        OrderPayment.is_deleted == False
    ).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment record not found")

    raw_amt = float(payload.get("amount") if "amount" in payload else (payment.amount or 0))
    p_type = (payload.get("payment_type") or payment.payment_type or "ADVANCE").strip().upper()

    if p_type == "RETURN":
        if raw_amt == 0:
            raise HTTPException(status_code=400, detail="Return payment amount cannot be zero.")
        amt = -abs(raw_amt)
    else:
        if raw_amt < 0:
            raise HTTPException(
                status_code=400,
                detail="Negative amounts are only acceptable when payment type is 'Return Payment'."
            )
        if raw_amt <= 0:
            raise HTTPException(status_code=400, detail="Payment amount must be greater than zero.")
        amt = raw_amt

    allow_overpayment = bool(payload.get("allow_overpayment", False))

    other_payments = db.query(OrderPayment).filter(
        OrderPayment.po_id == order.id,
        OrderPayment.id != payment.id,
        OrderPayment.is_deleted == False
    ).all()
    other_paid = sum(float(p.amount or 0) for p in other_payments)

    total_order = float(order.total_amount or 0)
    if total_order <= 0:
        items_total = sum(float(it.total_price or 0) for it in (order.items or []) if not getattr(it, 'is_deleted', False))
        if items_total > 0:
            total_order = items_total
            order.total_amount = items_total

    remaining_due = max(0.0, total_order - other_paid)

    if p_type == "RETURN":
        if abs(amt) > (other_paid + 0.01):
            raise HTTPException(
                status_code=400,
                detail=f"Return payment ({abs(amt):.2f}) cannot exceed the total amount already paid ({other_paid:.2f})."
            )
    else:
        if total_order > 0 and amt > (remaining_due + 0.01):
            if not allow_overpayment:
                raise HTTPException(
                    status_code=400,
                    detail=f"Payment amount ({amt:.2f}) exceeds the remaining order due ({remaining_due:.2f}). Overpayment is restricted without explicit authorization."
                )

    paid_d = payment.paid_date
    if "paid_date" in payload and payload["paid_date"]:
        try:
            paid_d = datetime.strptime(payload["paid_date"][:10], "%Y-%m-%d").date()
        except Exception:
            pass

    payment.payment_type = p_type
    payment.amount = amt
    if "currency" in payload and payload["currency"]:
        payment.currency = payload["currency"]
    payment.paid_date = paid_d
    payment.status = "RETURNED" if p_type == "RETURN" else "PAID"
    if "payment_method" in payload:
        payment.payment_method = payload["payment_method"]
    if "reference_number" in payload:
        payment.reference_number = payload["reference_number"]
    if "notes" in payload:
        payment.notes = payload["notes"]

    db.flush()

    # Recalculate accumulated active payments
    active_payments = db.query(OrderPayment).filter(
        OrderPayment.po_id == order.id,
        OrderPayment.is_deleted == False
    ).order_by(OrderPayment.id.desc()).all()
    total_paid = sum(float(p.amount or 0) for p in active_payments)

    order.advance_amount = total_paid
    order.balance_amount = max(0.0, total_order - total_paid)

    # Sync milestone payment dates based on active payments
    advance_payments = [p for p in active_payments if p.payment_type == "ADVANCE" and p.paid_date]
    if advance_payments:
        order.payment_date = min(p.paid_date for p in advance_payments)
    elif not any(p.paid_date for p in active_payments):
        order.payment_date = None

    balance_or_final = [p for p in active_payments if p.payment_type in ["BALANCE", "FINAL"] and p.paid_date]
    if balance_or_final:
        order.balance_payment_date = max(p.paid_date for p in balance_or_final)
    elif total_order > 0 and total_paid >= (total_order - 0.01):
        all_with_dates = [p for p in active_payments if p.paid_date]
        if all_with_dates:
            order.balance_payment_date = max(p.paid_date for p in all_with_dates)
    else:
        order.balance_payment_date = None

    if total_order > 0 and total_paid >= (total_order - 0.01):
        order.payment_status = "FULLY_PAID"
    elif total_paid > 0:
        order.payment_status = "PART_PAID"
    else:
        order.payment_status = "NONE"

    db.commit()
    db.refresh(payment)

    return {
        "success": True,
        "message": f"Payment #{payment.id} updated successfully for PO {order.po_number}",
        "payment": {
            "id": payment.id,
            "payment_type": payment.payment_type,
            "amount": float(payment.amount or 0),
            "currency": payment.currency,
            "paid_date": payment.paid_date.isoformat() if payment.paid_date else None,
            "payment_method": payment.payment_method,
            "reference_number": payment.reference_number,
            "notes": payment.notes,
            "status": payment.status,
            "created_at": payment.created_at.isoformat() if hasattr(payment, 'created_at') and payment.created_at else None,
        },
        "advance_amount": float(order.advance_amount or 0),
        "balance_amount": float(order.balance_amount or 0),
        "payment_status": order.payment_status,
        "payments": [
            {
                "id": pm.id,
                "payment_type": pm.payment_type,
                "amount": float(pm.amount or 0),
                "currency": pm.currency,
                "paid_date": pm.paid_date.isoformat() if pm.paid_date else None,
                "payment_method": pm.payment_method,
                "reference_number": pm.reference_number,
                "notes": pm.notes,
                "status": pm.status,
                "created_at": pm.created_at.isoformat() if hasattr(pm, 'created_at') and pm.created_at else None,
            }
            for pm in active_payments
        ]
    }

# ── Delete / Void Payments ───────────────────────────────────────────────────
@OrderRouter.delete("/{order_id}/payments/{payment_id}")
@OrderRouter.delete("/{order_id}/payments/{payment_id}/")
async def delete_payment(
    order_id: int,
    payment_id: int,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    if not is_accounts_user(current_user, org_context):
        raise HTTPException(status_code=403, detail="Only Accounts/Finance users can delete payments.")

    query = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id, PurchaseOrder.is_deleted == False)
    query = apply_org_filter(query, PurchaseOrder, org_context)
    order = query.first()
    if not order:
        raise HTTPException(status_code=404, detail="Purchase order not found")

    payment = db.query(OrderPayment).filter(
        OrderPayment.id == payment_id,
        OrderPayment.po_id == order.id,
        OrderPayment.is_deleted == False
    ).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment record not found")

    payment.is_deleted = True
    payment.status = "CANCELLED"
    db.flush()

    # Recalculate accumulated active payments
    active_payments = db.query(OrderPayment).filter(
        OrderPayment.po_id == order.id,
        OrderPayment.is_deleted == False
    ).order_by(OrderPayment.id.desc()).all()
    total_paid = sum(float(p.amount or 0) for p in active_payments)
    total_order = float(order.total_amount or 0)

    order.advance_amount = total_paid
    order.balance_amount = max(0.0, total_order - total_paid)

    if total_order > 0 and total_paid >= (total_order - 0.01):
        order.payment_status = "FULLY_PAID"
    elif total_paid > 0:
        order.payment_status = "PART_PAID"
    else:
        order.payment_status = "NONE"

    db.commit()
    sync_order_document(order)

    return {
        "success": True,
        "message": "Payment record deleted successfully",
        "advance_amount": float(order.advance_amount or 0),
        "balance_amount": float(order.balance_amount or 0),
        "payment_status": order.payment_status,
        "remaining_payments": [
            {
                "id": pm.id,
                "payment_type": pm.payment_type,
                "amount": float(pm.amount or 0),
                "currency": pm.currency,
                "paid_date": pm.paid_date.isoformat() if pm.paid_date else None,
                "payment_method": pm.payment_method,
                "reference_number": pm.reference_number,
                "notes": pm.notes,
                "status": pm.status,
                "created_at": pm.created_at.isoformat() if hasattr(pm, 'created_at') and pm.created_at else None,
            }
            for pm in active_payments
        ]
    }

# ── Upload Supporting Documents ───────────────────────────────────────────────
@OrderRouter.post("/{order_id}/documents")
async def upload_order_document(
    order_id: int,
    file: UploadFile = File(...),
    doc_type: str = Form("OTHER"),
    title: Optional[str] = Form(None),
    is_confidential: bool = Form(False),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    query = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id, PurchaseOrder.is_deleted == False)
    query = apply_org_filter(query, PurchaseOrder, org_context)
    order = query.first()
    if not order:
        raise HTTPException(status_code=404, detail="Purchase order not found")

    file_bytes = await file.read()
    key = blob_storage.upload_file(
        file_bytes=file_bytes,
        file_name=file.filename,
        folder=f"orders/{order.po_number}"
    )

    doc = OrderDocument(
        entity_type="PO",
        entity_id=order.id,
        po_id=order.id,
        doc_type=doc_type,
        title=title or file.filename,
        file_name=file.filename,
        file_path=key,
        file_size=len(file_bytes),
        mime_type=file.content_type,
        is_confidential=is_confidential,
        notes=notes,
        created_by=current_user.id
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return {"success": True, "document_id": doc.id, "file_path": key}

@OrderRouter.delete("/{order_id}")
async def delete_order(
    order_id: int,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    query = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id, PurchaseOrder.is_deleted == False)
    query = apply_org_filter(query, PurchaseOrder, org_context)
    order = query.first()
    if not order:
        raise HTTPException(status_code=404, detail="Purchase order not found")

    is_accounts = is_accounts_user(current_user, org_context)
    order_doc_type = (getattr(order, "doc_type", "PO") or "PO").upper()
    if order_doc_type == "RFQ":
        if not (has_permission(current_user, "Delete_RFQ") or has_permission(current_user, "Delete_Order") or is_accounts):
            raise HTTPException(status_code=403, detail="Operation forbidden: Missing required permission 'Delete_RFQ'.")
    else:
        if not (has_permission(current_user, "Delete_Order") or is_accounts):
            raise HTTPException(status_code=403, detail="Operation forbidden: Missing required permission 'Delete_Order'.")

    order.is_deleted = True
    order.deleted_at = datetime.utcnow()
    order.deleted_by = current_user.id
    db.commit()
    remove_order_document(order.id)
    logger.info("Deleted PO %s by %s", order.po_number, current_user.username)
    return {"success": True, "message": f"Order {order.po_number} deleted successfully"}

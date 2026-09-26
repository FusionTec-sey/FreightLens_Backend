import logging
from datetime import datetime, date
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, and_, desc, asc
import math

from Model.db import get_db
from Model.containermgmt.Orders.PurchaseOrder import PurchaseOrder
from Model.containermgmt.Orders.GoodsReceipt import GoodsReceipt, ReceiptItem
from Model.containermgmt.Orders.POItem import POItem
from Model.containermgmt.Orders.OrderPackingList import OrderPackingList, PackingListItem
from Model.containermgmt.Orders.OrderStatus import OrderStatus
from Model.containermgmt.Orders.Notification import Notification
from Model.containermgmt.Container.ContainerDetails import ContainerDetails
from Model.Credentials.users import User
from auth.dependencies import get_current_user, get_org_context
from Utils.org_filter import OrgContext, apply_org_filter

logger = logging.getLogger("containerMgmt.orders.receiving")

ReceivingRouter = APIRouter(prefix="/goods-receiving", tags=["Goods Receiving"])

def format_receipt(gr: GoodsReceipt) -> dict:
    return {
        "id": gr.id,
        "receipt_number": gr.receipt_number,
        "po_id": gr.po_id,
        "po_number": gr.purchase_order.po_number if gr.purchase_order else None,
        "packing_list_id": gr.packing_list_id,
        "container_id": gr.container_id,
        "container_no": gr.container.container_no if gr.container else None,
        "warehouse_location": gr.warehouse_location,
        "received_date": gr.received_date.isoformat() if gr.received_date else None,
        "status": gr.status,
        "has_discrepancies": bool(gr.has_discrepancies),
        "notes": gr.notes,
        "submitted_at": gr.submitted_at.isoformat() if gr.submitted_at else None,
        "receiver_name": gr.receiver.username if gr.receiver else None,
        "items": [
            {
                "id": it.id,
                "po_item_id": it.po_item_id,
                "packing_item_id": it.packing_item_id,
                "description": it.description,
                "expected_quantity": float(it.expected_quantity or 0),
                "received_quantity": float(it.received_quantity or 0),
                "missing_quantity": float(it.missing_quantity or 0),
                "excess_quantity": float(it.excess_quantity or 0),
                "damaged_quantity": float(it.damaged_quantity or 0),
                "incorrect_quantity": float(it.incorrect_quantity or 0),
                "unit": it.unit,
                "condition_ok": bool(it.condition_ok),
                "notes": it.notes,
                "photo_url": it.photo_url,
            }
            for it in (gr.items or []) if not it.is_deleted
        ]
    }

@ReceivingRouter.get("")
@ReceivingRouter.get("/")
async def list_receipts(
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=100),
    sort_by: Optional[str] = Query(None),
    sort_dir: Optional[str] = Query("desc"),
    po_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    offset = (page - 1) * limit
    query = (
        db.query(GoodsReceipt)
        .options(
            joinedload(GoodsReceipt.purchase_order),
            joinedload(GoodsReceipt.container),
            joinedload(GoodsReceipt.receiver),
            joinedload(GoodsReceipt.items)
        )
        .filter(GoodsReceipt.is_deleted == False)
    )
    query = apply_org_filter(query, GoodsReceipt, org_context)

    if po_id:
        query = query.filter(GoodsReceipt.po_id == po_id)

    if status and status != "ALL":
        query = query.filter(GoodsReceipt.status == status)

    if search:
        s = f"%{search.strip()}%"
        query = query.filter(
            or_(
                GoodsReceipt.receipt_number.ilike(s),
                GoodsReceipt.warehouse_location.ilike(s)
            )
        )

    total_count = query.count()

    ALLOWED_SORT = {
        "id": GoodsReceipt.id,
        "receipt_number": GoodsReceipt.receipt_number,
        "receipt_date": GoodsReceipt.receipt_date,
        "status": GoodsReceipt.status,
        "created_at": GoodsReceipt.created_at,
    }
    sort_column = ALLOWED_SORT.get(sort_by, GoodsReceipt.id)
    if sort_dir == "asc":
        query = query.order_by(asc(sort_column))
    else:
        query = query.order_by(desc(sort_column))

    receipts = query.offset(offset).limit(limit).all()
    return {
        "items": [format_receipt(r) for r in receipts],
        "total": total_count,
        "page": page,
        "limit": limit,
        "pages": math.ceil(total_count / limit) if total_count > 0 else 1
    }

@ReceivingRouter.get("/{receipt_id}")
async def get_receipt(
    receipt_id: int,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    query = (
        db.query(GoodsReceipt)
        .options(
            joinedload(GoodsReceipt.purchase_order),
            joinedload(GoodsReceipt.container),
            joinedload(GoodsReceipt.receiver),
            joinedload(GoodsReceipt.items)
        )
        .filter(GoodsReceipt.id == receipt_id, GoodsReceipt.is_deleted == False)
    )
    query = apply_org_filter(query, GoodsReceipt, org_context)
    gr = query.first()
    if not gr:
        raise HTTPException(status_code=404, detail="Goods receipt not found")
    return format_receipt(gr)

@ReceivingRouter.post("")
@ReceivingRouter.post("/")
async def create_receipt(
    payload: dict,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    po_id = payload.get("po_id")
    if not po_id:
        raise HTTPException(status_code=422, detail="PO ID is required")

    po = db.query(PurchaseOrder).filter(PurchaseOrder.id == po_id, PurchaseOrder.is_deleted == False).first()
    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")

    rec_num = payload.get("receipt_number", "").strip() or f"GRN-{datetime.utcnow().strftime('%Y%m%d')}-{po.id}"
    rec_date = datetime.strptime(payload["received_date"][:10], "%Y-%m-%d").date() if payload.get("received_date") else date.today()

    new_gr = GoodsReceipt(
        receipt_number=rec_num,
        po_id=po.id,
        packing_list_id=payload.get("packing_list_id"),
        container_id=payload.get("container_id"),
        warehouse_location=payload.get("warehouse_location", "").strip() or None,
        received_date=rec_date,
        received_by=current_user.id,
        status=payload.get("status", "DRAFT"),
        has_discrepancies=bool(payload.get("has_discrepancies", False)),
        notes=payload.get("notes", "").strip() or None,
        org_id=po.org_id,
        created_by=current_user.id
    )
    db.add(new_gr)
    db.flush()

    has_any_discrepancy = False
    for it in payload.get("items", []):
        exp_qty = float(it.get("expected_quantity") or 0)
        rec_qty = float(it.get("received_quantity") or 0)
        missing_qty = float(it.get("missing_quantity") or 0)
        excess_qty = float(it.get("excess_quantity") or 0)
        damaged_qty = float(it.get("damaged_quantity") or 0)
        incorrect_qty = float(it.get("incorrect_quantity") or 0)

        if missing_qty > 0 or excess_qty > 0 or damaged_qty > 0 or incorrect_qty > 0:
            has_any_discrepancy = True

        rec_item = ReceiptItem(
            receipt_id=new_gr.id,
            po_item_id=it.get("po_item_id"),
            packing_item_id=it.get("packing_item_id"),
            description=it.get("description", "").strip(),
            expected_quantity=exp_qty,
            received_quantity=rec_qty,
            missing_quantity=missing_qty,
            excess_quantity=excess_qty,
            damaged_quantity=damaged_qty,
            incorrect_quantity=incorrect_qty,
            unit=it.get("unit", "PCS"),
            condition_ok=bool(it.get("condition_ok", True)),
            notes=it.get("notes", "").strip() or None,
            photo_url=it.get("photo_url"),
            created_by=current_user.id
        )
        db.add(rec_item)

        # Update PO Item received quantity
        if it.get("po_item_id"):
            po_item = db.query(POItem).filter(POItem.id == it["po_item_id"]).first()
            if po_item:
                po_item.quantity_received = float(po_item.quantity_received or 0) + rec_qty

    new_gr.has_discrepancies = has_any_discrepancy

    # If submitted, update PO status to RECEIVED / COMPLETED
    if new_gr.status == "SUBMITTED":
        new_gr.submitted_at = datetime.utcnow()
        po.receipt_status = "RECEIVED"
        received_st = db.query(OrderStatus).filter(OrderStatus.code == "RECEIVED").first()
        if received_st:
            po.status_id = received_st.id
            po.status = "RECEIVED"
            po.status_label = "Received"

        notif = Notification(
            org_id=po.org_id,
            event_type="GOODS_RECEIVED",
            title="Goods Received at Warehouse",
            message=f"Warehouse completed receiving for PO {po.po_number}. Receipt #{new_gr.receipt_number}.",
            link_entity_type="RECEIPT",
            link_entity_id=new_gr.id
        )
        db.add(notif)

    db.commit()
    db.refresh(new_gr)
    return format_receipt(new_gr)

@ReceivingRouter.post("/{receipt_id}/submit")
async def submit_receipt(
    receipt_id: int,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    query = db.query(GoodsReceipt).filter(GoodsReceipt.id == receipt_id, GoodsReceipt.is_deleted == False)
    query = apply_org_filter(query, GoodsReceipt, org_context)
    gr = query.first()
    if not gr:
        raise HTTPException(status_code=404, detail="Goods receipt not found")

    gr.status = "SUBMITTED"
    gr.submitted_at = datetime.utcnow()
    gr.updated_by = current_user.id

    po = db.query(PurchaseOrder).filter(PurchaseOrder.id == gr.po_id).first()
    if po:
        po.receipt_status = "RECEIVED"
        received_st = db.query(OrderStatus).filter(OrderStatus.code == "RECEIVED").first()
        if received_st:
            po.status_id = received_st.id
            po.status = "RECEIVED"
            po.status_label = "Received"

    db.commit()
    return format_receipt(gr)

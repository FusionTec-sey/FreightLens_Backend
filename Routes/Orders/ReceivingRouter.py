import logging
from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, desc, asc
import math
from uuid import uuid4
from sqlalchemy.exc import IntegrityError
from pydantic import ValidationError
from Schema.ReceivingSchema import ReceiptCreate, ReceiptLineCreate
from Services.receiving_service import lock_order, validate_links, post_receipt
from auth.security_guards import require_permission, has_permission

from Model.db import get_db
from Model.containermgmt.Orders.PurchaseOrder import PurchaseOrder
from Model.containermgmt.Orders.GoodsReceipt import GoodsReceipt, ReceiptItem
from Model.containermgmt.Orders.POItem import POItem
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
        "requires_quantity_review": gr.posting_version != 1 and gr.status != "SUBMITTED",
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

@ReceivingRouter.get("", dependencies=[Depends(require_permission("View_GoodsReceipt"))])
@ReceivingRouter.get("/", dependencies=[Depends(require_permission("View_GoodsReceipt"))])
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
        "receipt_date": GoodsReceipt.received_date,
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

@ReceivingRouter.get("/{receipt_id}", dependencies=[Depends(require_permission("View_GoodsReceipt"))])
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

@ReceivingRouter.post("", dependencies=[Depends(require_permission("Verify_Receipt"))])
@ReceivingRouter.post("/", dependencies=[Depends(require_permission("Verify_Receipt"))])
async def create_receipt(
    payload: ReceiptCreate,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user),
):
    if payload.status == "SUBMITTED" and not has_permission(current_user, "Submit_Receipt"):
        raise HTTPException(403, "Submit_Receipt permission is required")
    try:
        po = lock_order(db, payload.po_id, org_context)
        items = validate_links(db, po, payload, payload.items)
        values = payload.model_dump(exclude={"items", "has_discrepancies"})
        values["receipt_number"] = payload.receipt_number or f"GRN-{date.today():%Y%m%d}-{uuid4().hex}"
        new_gr = GoodsReceipt(
            **values, org_id=po.org_id, created_by=current_user.id,
            received_by=current_user.id, posting_version=1,
        )
        new_gr.has_discrepancies = any(
            not line.condition_ok or any(getattr(line, field) > 0 for field in
                ("missing_quantity", "excess_quantity", "damaged_quantity", "incorrect_quantity"))
            for line in payload.items
        )
        db.add(new_gr)
        db.flush()
        for line in payload.items:
            db.add(ReceiptItem(**line.model_dump(), receipt_id=new_gr.id, created_by=current_user.id))
        if payload.status == "SUBMITTED":
            post_receipt(db, po, new_gr, payload.items, items, current_user.id)
        db.commit()
        db.refresh(new_gr)
        return format_receipt(new_gr)
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Receipt conflicts with existing data; reload before retrying")
    except Exception:
        db.rollback()
        raise


@ReceivingRouter.post("/{receipt_id}/submit", dependencies=[Depends(require_permission("Submit_Receipt"))])
async def submit_receipt(
    receipt_id: int,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user),
):
    try:
        query = apply_org_filter(
            db.query(GoodsReceipt).filter(GoodsReceipt.id == receipt_id, GoodsReceipt.is_deleted == False),
            GoodsReceipt, org_context,
        )
        initial = query.first()
        if initial is None:
            raise HTTPException(404, "Goods receipt not found")
        po = lock_order(db, initial.po_id, org_context)
        # Refresh after waiting for the PO lock: another submission may have committed.
        gr = query.with_for_update(of=GoodsReceipt).populate_existing().first()
        if gr is None or gr.org_id != po.org_id or gr.po_id != po.id:
            raise HTTPException(404, "Goods receipt not found")
        if gr.status == "SUBMITTED":
            db.commit()
            return format_receipt(gr)
        if gr.status != "DRAFT":
            raise HTTPException(409, "Only draft receipts can be submitted")
        if gr.posting_version != 1:
            raise HTTPException(409, "Legacy receipt requires quantity reconciliation before submission")
        # Revalidate stored lines as well as new requests.
        lines = [ReceiptLineCreate.model_validate({
            name: getattr(line, name) for name in ReceiptLineCreate.model_fields
        }) for line in gr.items if not line.is_deleted]
        items = validate_links(db, po, gr, lines)
        post_receipt(db, po, gr, lines, items, current_user.id)
        db.commit()
        return format_receipt(gr)
    except ValidationError:
        db.rollback()
        raise HTTPException(409, "Stored receipt lines require correction before submission")
    except Exception:
        db.rollback()
        raise

import logging
from datetime import datetime, date
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, and_, desc

from Model.db import get_db
from Model.containermgmt.Orders.PurchaseOrder import PurchaseOrder
from Model.containermgmt.Orders.OrderPackingList import OrderPackingList, PackingListItem
from Model.containermgmt.Orders.POItem import POItem
from Model.containermgmt.Orders.OrderStatus import OrderStatus
from Model.Credentials.users import User
from auth.dependencies import get_current_user, get_org_context
from Utils.org_filter import OrgContext, apply_org_filter

logger = logging.getLogger("containerMgmt.orders.packing")

PackingListRouter = APIRouter(prefix="/packing-lists", tags=["Packing Lists"])

def format_packing_list(pl: OrderPackingList) -> dict:
    return {
        "id": pl.id,
        "po_id": pl.po_id,
        "po_number": pl.purchase_order.po_number if pl.purchase_order else None,
        "packing_list_number": pl.packing_list_number,
        "supplier_invoice_ref": pl.supplier_invoice_ref,
        "package_count": pl.package_count,
        "total_gross_weight": float(pl.total_gross_weight or 0),
        "total_cbm": float(pl.total_cbm or 0),
        "date_issued": pl.date_issued.isoformat() if pl.date_issued else None,
        "status": pl.status,
        "notes": pl.notes,
        "items": [
            {
                "id": it.id,
                "po_item_id": it.po_item_id,
                "item_code": it.item_code,
                "description": it.description,
                "quantity_packed": float(it.quantity_packed or 0),
                "unit": it.unit,
                "carton_numbers": it.carton_numbers,
                "notes": it.notes,
            }
            for it in (pl.items or []) if not it.is_deleted
        ]
    }

@PackingListRouter.get("")
@PackingListRouter.get("/")
async def list_packing_lists(
    po_id: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    query = (
        db.query(OrderPackingList)
        .join(PurchaseOrder, OrderPackingList.po_id == PurchaseOrder.id)
        .options(joinedload(OrderPackingList.purchase_order), joinedload(OrderPackingList.items))
        .filter(OrderPackingList.is_deleted == False, PurchaseOrder.is_deleted == False)
    )
    query = apply_org_filter(query, PurchaseOrder, org_context)

    if po_id:
        query = query.filter(OrderPackingList.po_id == po_id)

    if search:
        s = f"%{search.strip()}%"
        query = query.filter(
            or_(
                OrderPackingList.packing_list_number.ilike(s),
                OrderPackingList.supplier_invoice_ref.ilike(s),
                PurchaseOrder.po_number.ilike(s)
            )
        )

    lists = query.order_by(desc(OrderPackingList.id)).all()
    return [format_packing_list(pl) for pl in lists]

@PackingListRouter.get("/{packing_id}")
async def get_packing_list(
    packing_id: int,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    query = (
        db.query(OrderPackingList)
        .join(PurchaseOrder, OrderPackingList.po_id == PurchaseOrder.id)
        .options(joinedload(OrderPackingList.purchase_order), joinedload(OrderPackingList.items))
        .filter(OrderPackingList.id == packing_id, OrderPackingList.is_deleted == False)
    )
    query = apply_org_filter(query, PurchaseOrder, org_context)
    pl = query.first()
    if not pl:
        raise HTTPException(status_code=404, detail="Packing list not found")
    return format_packing_list(pl)

@PackingListRouter.post("")
@PackingListRouter.post("/")
async def create_packing_list(
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

    pl_number = payload.get("packing_list_number", "").strip() or f"PL-{po.po_number}"

    new_pl = OrderPackingList(
        po_id=po.id,
        packing_list_number=pl_number,
        supplier_invoice_ref=payload.get("supplier_invoice_ref", "").strip() or None,
        package_count=payload.get("package_count"),
        total_gross_weight=payload.get("total_gross_weight"),
        total_cbm=payload.get("total_cbm"),
        date_issued=datetime.strptime(payload["date_issued"][:10], "%Y-%m-%d").date() if payload.get("date_issued") else None,
        status="CONFIRMED",
        notes=payload.get("notes", "").strip() or None,
        created_by=current_user.id
    )
    db.add(new_pl)
    db.flush()

    for item in payload.get("items", []):
        desc_text = item.get("description", "").strip()
        if not desc_text: continue
        qty_packed = float(item.get("quantity_packed") or 1.0)
        po_it_id = item.get("po_item_id")
        
        pl_it = PackingListItem(
            packing_list_id=new_pl.id,
            po_item_id=po_it_id,
            item_code=item.get("item_code", "").strip() or None,
            description=desc_text,
            quantity_packed=qty_packed,
            unit=item.get("unit", "PCS"),
            carton_numbers=item.get("carton_numbers", "").strip() or None,
            notes=item.get("notes", "").strip() or None,
            created_by=current_user.id
        )
        db.add(pl_it)

        # Update PO Item packed quantity
        if po_it_id:
            po_item = db.query(POItem).filter(POItem.id == po_it_id).first()
            if po_item:
                po_item.quantity_packed = float(po_item.quantity_packed or 0) + qty_packed

    # Update PO status to PACKED if not yet shipped
    if po.status in ["ORDERED", "IN_PRODUCTION", "READY"]:
        packed_st = db.query(OrderStatus).filter(OrderStatus.code == "PACKED").first()
        if packed_st:
            po.status_id = packed_st.id
            po.status = "PACKED"
            po.status_label = "Packed"

    db.commit()
    db.refresh(new_pl)
    return format_packing_list(new_pl)

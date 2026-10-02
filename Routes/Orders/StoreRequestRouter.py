import logging
from datetime import datetime, date
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, and_, desc, asc
import math

from Model.db import get_db
from Model.containermgmt.Orders.StoreRequest import StoreRequest, StoreRequestItem
from Model.containermgmt.Orders.OrderStatusHistory import OrderStatusHistory
from Model.containermgmt.Orders.Notification import Notification
from Model.Credentials.users import User
from auth.dependencies import get_current_user, get_org_context
from auth.security_guards import is_financial_user
from Utils.org_filter import OrgContext, apply_org_filter
from Utils.blob_storage import blob_storage

logger = logging.getLogger("containerMgmt.orders.requests")

StoreRequestRouter = APIRouter(prefix="/store-requests", tags=["Store Requests"])


def _signed_item_image(image_url: Optional[str]) -> Optional[str]:
    if not image_url or image_url.startswith(("http://", "https://", "blob:", "data:")):
        return image_url
    return blob_storage.signed_url(image_url, ttl=24 * 60 * 60)

def format_request(req: StoreRequest, is_accounts: bool = True) -> dict:
    return {
        "id": req.id,
        "request_number": req.request_number,
        "title": req.title,
        "department": req.department,
        "store_location": req.store_location,
        "status": req.status,
        "status_label": req.status_label,
        "required_date": req.required_date.isoformat() if req.required_date else None,
        "notes": req.notes,
        "org_id": req.org_id,
        "submitted_at": req.submitted_at.isoformat() if req.submitted_at else None,
        "submitted_by": req.submitted_by,
        "created_at": req.created_at.isoformat() if req.created_at else None,
        "items": [
            {
                "id": item.id,
                "item_code": item.item_code,
                "description": item.description,
                "quantity_requested": float(item.quantity_requested or 0),
                "quantity_ordered": float(item.quantity_ordered or 0),
                "quantity_received": float(item.quantity_received or 0),
                "unit": item.unit,
                "required_date": item.required_date.isoformat() if item.required_date else None,
                "notes": item.notes,
                "image_url": item.image_url,
                "image_signed_url": _signed_item_image(item.image_url),
            }
            for item in req.items if not item.is_deleted
        ],
        "purchase_orders": [
            {
                "id": po.id,
                "po_number": po.po_number,
                "doc_type": po.doc_type,
                "status": po.status,
                "status_label": po.status_label,
                "lifecycle_stage": po.lifecycle_stage,
                "eta_date": po.eta_date.isoformat() if po.eta_date else None,
            }
            for po in (req.purchase_orders or []) if not po.is_deleted
        ]
    }

def generate_request_number(db: Session, org_id: int) -> str:
    year = datetime.utcnow().year
    prefix = f"REQ-{year}-"
    count = db.query(StoreRequest).filter(StoreRequest.request_number.like(f"{prefix}%")).count()
    return f"{prefix}{count + 1:04d}"

@StoreRequestRouter.get("")
@StoreRequestRouter.get("/")
async def list_store_requests(
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=100),
    sort_by: Optional[str] = Query(None),
    sort_dir: Optional[str] = Query("desc"),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    offset = (page - 1) * limit
    query = (
        db.query(StoreRequest)
        .options(joinedload(StoreRequest.items))
        .filter(StoreRequest.is_deleted == False)
    )
    query = apply_org_filter(query, StoreRequest, org_context)

    if status and status != "ALL":
        query = query.filter(StoreRequest.status == status)

    if search:
        s = f"%{search.strip()}%"
        query = query.filter(
            or_(
                StoreRequest.request_number.ilike(s),
                StoreRequest.title.ilike(s),
                StoreRequest.department.ilike(s),
                StoreRequest.store_location.ilike(s)
            )
        )

    total_count = query.count()

    ALLOWED_SORT = {
        "id": StoreRequest.id,
        "request_number": StoreRequest.request_number,
        "title": StoreRequest.title,
        "status": StoreRequest.status,
        "created_at": StoreRequest.created_at,
    }
    sort_column = ALLOWED_SORT.get(sort_by, StoreRequest.id)
    if sort_dir == "asc":
        query = query.order_by(asc(sort_column))
    else:
        query = query.order_by(desc(sort_column))

    requests = query.offset(offset).limit(limit).all()
    is_accounts = is_financial_user(current_user, org_context)
    return {
        "items": [format_request(r, is_accounts) for r in requests],
        "total": total_count,
        "page": page,
        "limit": limit,
        "pages": math.ceil(total_count / limit) if total_count > 0 else 1
    }

@StoreRequestRouter.get("/{request_id}")
async def get_store_request(
    request_id: int,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    query = (
        db.query(StoreRequest)
        .options(joinedload(StoreRequest.items))
        .filter(StoreRequest.id == request_id, StoreRequest.is_deleted == False)
    )
    query = apply_org_filter(query, StoreRequest, org_context)
    req = query.first()
    if not req:
        raise HTTPException(status_code=404, detail="Store request not found")

    is_accounts = is_financial_user(current_user, org_context)
    return format_request(req, is_accounts)

@StoreRequestRouter.post("")
@StoreRequestRouter.post("/")
async def create_store_request(
    payload: dict,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    requested_org_id = payload.get("org_id")
    if requested_org_id is not None and requested_org_id not in org_context.allowed_org_ids:
        raise HTTPException(status_code=403, detail="Organisation is not available to this user")
    target_org_id = requested_org_id or org_context.org_id

    req_number = payload.get("request_number") or generate_request_number(db, target_org_id)
    
    new_req = StoreRequest(
        request_number=req_number,
        title=payload.get("title", "").strip() or None,
        department=payload.get("department", "").strip() or None,
        store_location=payload.get("store_location", "").strip() or None,
        status="DRAFT",
        status_label="Draft",
        required_date=datetime.strptime(payload["required_date"][:10], "%Y-%m-%d").date() if payload.get("required_date") else None,
        notes=payload.get("notes", "").strip() or None,
        org_id=target_org_id,
        created_by=current_user.id
    )
    db.add(new_req)
    db.flush()

    # Add items
    items_data = payload.get("items", [])
    for item in items_data:
        desc_text = item.get("description", "").strip()
        if not desc_text:
            continue
        req_item = StoreRequestItem(
            request_id=new_req.id,
            item_code=item.get("item_code", "").strip() or None,
            description=desc_text,
            quantity_requested=float(item.get("quantity_requested") or 1.0),
            unit=item.get("unit", "PCS"),
            required_date=datetime.strptime(item["required_date"][:10], "%Y-%m-%d").date() if item.get("required_date") else None,
            notes=item.get("notes", "").strip() or None,
            image_url=item.get("image_url"),
            created_by=current_user.id
        )
        db.add(req_item)

    db.commit()
    db.refresh(new_req)
    logger.info("Created store request %s by %s", new_req.request_number, current_user.username)
    return format_request(new_req)

@StoreRequestRouter.put("/{request_id}")
async def update_store_request(
    request_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    query = db.query(StoreRequest).filter(StoreRequest.id == request_id, StoreRequest.is_deleted == False)
    query = apply_org_filter(query, StoreRequest, org_context)
    req = query.first()
    if not req:
        raise HTTPException(status_code=404, detail="Store request not found")

    if req.status not in ["DRAFT", "WITHDRAWN"]:
        raise HTTPException(status_code=400, detail="Cannot edit a submitted or locked request. Withdraw or request return to draft.")

    if "title" in payload:
        req.title = payload["title"].strip() or None
    if "department" in payload:
        req.department = payload["department"].strip() or None
    if "store_location" in payload:
        req.store_location = payload["store_location"].strip() or None
    if "required_date" in payload:
        req.required_date = datetime.strptime(payload["required_date"][:10], "%Y-%m-%d").date() if payload["required_date"] else None
    if "notes" in payload:
        req.notes = payload["notes"].strip() or None

    req.updated_by = current_user.id

    # Update items if provided
    if "items" in payload:
        # Soft delete existing items
        for old_item in req.items:
            old_item.is_deleted = True
        
        for item in payload["items"]:
            desc_text = item.get("description", "").strip()
            if not desc_text:
                continue
            req_item = StoreRequestItem(
                request_id=req.id,
                item_code=item.get("item_code", "").strip() or None,
                description=desc_text,
                quantity_requested=float(item.get("quantity_requested") or 1.0),
                unit=item.get("unit", "PCS"),
                required_date=datetime.strptime(item["required_date"][:10], "%Y-%m-%d").date() if item.get("required_date") else None,
                notes=item.get("notes", "").strip() or None,
                image_url=item.get("image_url"),
                created_by=current_user.id
            )
            db.add(req_item)

    db.commit()
    db.refresh(req)
    return format_request(req)

@StoreRequestRouter.post("/{request_id}/submit")
async def submit_store_request(
    request_id: int,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    query = db.query(StoreRequest).filter(StoreRequest.id == request_id, StoreRequest.is_deleted == False)
    query = apply_org_filter(query, StoreRequest, org_context)
    req = query.first()
    if not req:
        raise HTTPException(status_code=404, detail="Store request not found")

    if req.status == "SUBMITTED":
        return format_request(req)

    req.status = "SUBMITTED"
    req.status_label = "Submitted"
    req.submitted_at = datetime.utcnow()
    req.submitted_by = current_user.id
    req.updated_by = current_user.id

    # Add notification for Accounts/Management
    notif = Notification(
        org_id=req.org_id,
        event_type="REQUEST_SUBMITTED",
        title="New Store Request Submitted",
        message=f"Store request {req.request_number} ({req.title or 'Items'}) was submitted by {current_user.username}.",
        link_entity_type="REQUEST",
        link_entity_id=req.id
    )
    db.add(notif)
    db.commit()
    db.refresh(req)
    return format_request(req)

@StoreRequestRouter.post("/{request_id}/withdraw")
async def withdraw_store_request(
    request_id: int,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    query = db.query(StoreRequest).filter(StoreRequest.id == request_id, StoreRequest.is_deleted == False)
    query = apply_org_filter(query, StoreRequest, org_context)
    req = query.first()
    if not req:
        raise HTTPException(status_code=404, detail="Store request not found")

    if req.status == "ORDERED":
        raise HTTPException(status_code=400, detail="Cannot withdraw request after a Supplier PO has already been created. Contact Accounts.")

    req.status = "WITHDRAWN"
    req.status_label = "Withdrawn (Draft)"
    req.updated_by = current_user.id
    db.commit()
    db.refresh(req)
    return format_request(req)

@StoreRequestRouter.delete("/{request_id}")
async def delete_store_request(
    request_id: int,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user)
):
    query = db.query(StoreRequest).filter(StoreRequest.id == request_id, StoreRequest.is_deleted == False)
    query = apply_org_filter(query, StoreRequest, org_context)
    req = query.first()
    if not req:
        raise HTTPException(status_code=404, detail="Store request not found")

    if req.status not in ["DRAFT", "WITHDRAWN"]:
        raise HTTPException(status_code=400, detail="Only Draft or Withdrawn requests can be deleted.")

    req.is_deleted = True
    req.deleted_at = datetime.utcnow()
    req.deleted_by = current_user.id
    db.commit()
    return {"success": True, "message": f"Request {req.request_number} deleted successfully"}

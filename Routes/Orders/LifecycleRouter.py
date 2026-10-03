import logging
from decimal import Decimal
from typing import Optional, List, Dict, Any
from datetime import date, datetime
from fastapi import APIRouter, Depends, HTTPException, Query, Body, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, field_validator
from sqlalchemy import or_

from Model.db import get_db
from Model.containermgmt.Orders.PurchaseOrder import PurchaseOrder
from Model.containermgmt.Orders.POItem import POItem
from Model.containermgmt.Orders.POItemHistory import POItemHistory
from Model.containermgmt.Orders.POVersionSnapshot import POVersionSnapshot
from Model.containermgmt.Orders.VendorQuote import VendorQuote
from Model.containermgmt.Orders.VendorQuoteItem import VendorQuoteItem
from Model.containermgmt.Cinfo.Supplier import Supplier
from Model.Credentials.users import User
from auth.dependencies import get_current_user, get_org_context
from auth.security_guards import (
    require_financial_access,
    is_financial_user,
    has_permission,
    require_sourcing_permission,
    can_access_sourcing
)
from Utils.org_filter import OrgContext, apply_org_filter

from .LifecycleService import LifecycleService, LIFECYCLE_SEQUENCE, STAGE_TITLES
from .QuoteComparisonService import QuoteComparisonService

logger = logging.getLogger("containerMgmt.lifecycle_router")

LifecycleRouter = APIRouter(prefix="/orders", tags=["PO Lifecycle & Quotes"])

# ── Pydantic Request Schemas ──────────────────────────────────────────────────

class StageTransitionRequest(BaseModel):
    target_stage: str
    expected_version: int
    comment: Optional[str] = None

class QuoteItemInput(BaseModel):
    po_item_id: Optional[int] = None
    inventory_product_id: Optional[int] = None
    item_code: Optional[str] = None
    description: str
    quantity_quoted: float
    unit_price: float
    availability: Optional[str] = "AVAILABLE"
    lead_time_days: Optional[int] = None
    is_substitute: Optional[bool] = False
    notes: Optional[str] = None

    @field_validator("lead_time_days", mode="before")
    def empty_int_to_none(cls, v):
        return None if v == "" or v is None else v

    @field_validator("quantity_quoted", "unit_price", mode="before")
    def empty_float_to_zero(cls, v):
        return 0.0 if v == "" or v is None else v

class VendorQuoteCreateRequest(BaseModel):
    supplier_id: int
    quote_reference: Optional[str] = None
    quote_date: Optional[date] = None
    valid_until: Optional[date] = None
    delivery_lead_time_days: Optional[int] = None
    payment_terms: Optional[str] = None
    shipping_terms: Optional[str] = None
    score_notes: Optional[str] = None
    currency: Optional[str] = "USD"
    items: List[QuoteItemInput]

    @field_validator("quote_date", "valid_until", "delivery_lead_time_days", mode="before")
    def empty_fields_to_none(cls, v):
        return None if v == "" or v is None else v

class VendorQuoteUpdateRequest(BaseModel):
    supplier_id: Optional[int] = None
    quote_reference: Optional[str] = None
    quote_date: Optional[date] = None
    valid_until: Optional[date] = None
    delivery_lead_time_days: Optional[int] = None
    payment_terms: Optional[str] = None
    shipping_terms: Optional[str] = None
    score_notes: Optional[str] = None
    currency: Optional[str] = "USD"
    items: Optional[List[QuoteItemInput]] = None

    @field_validator("quote_date", "valid_until", "delivery_lead_time_days", mode="before")
    def empty_fields_to_none(cls, v):
        return None if v == "" or v is None else v

class QuoteAwardRequest(BaseModel):
    line_awards: Optional[List[Dict[str, Any]]] = None

class SplitAwardAllocation(BaseModel):
    po_item_id: int
    quote_id: int
    unit_price: Optional[float] = None

class SplitAwardRequest(BaseModel):
    allocations: List[SplitAwardAllocation]

class VarianceApprovalRequest(BaseModel):
    justification: str

def check_variance_permission(user: User, org_context: OrgContext):
    if has_permission(user, "Approve_Variance"):
        return True
    raise HTTPException(
        status_code=403,
        detail="Permission Denied: 'Approve_Variance' is required."
    )

# ── Endpoints ─────────────────────────────────────────────────────────────────

@LifecycleRouter.get("/{po_id}/lifecycle")
def get_order_lifecycle(
    po_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context)
):
    """
    Returns current lifecycle stage, gate readiness checklist, and mutation warning level.
    """
    po_query = db.query(PurchaseOrder).filter(PurchaseOrder.id == po_id, PurchaseOrder.is_deleted == False)
    po = apply_org_filter(po_query, PurchaseOrder, org_context).first()
    if not po:
        raise HTTPException(status_code=404, detail="Purchase Order not found.")

    checklist = LifecycleService.get_gate_checklist(po, db)
    variance_info = LifecycleService.check_proforma_variance(po, db)

    # Recent transitions log
    transitions = [
        {
            "id": t.id,
            "from_stage": t.from_stage,
            "to_stage": t.to_stage,
            "from_version": t.from_version,
            "to_version": t.to_version,
            "transition_type": t.transition_type,
            "comment": t.comment,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "created_by": t.created_by
        }
        for t in (po.stage_transitions or [])[:10]
    ]

    return {
        "po_id": po.id,
        "po_number": po.po_number,
        **checklist,
        "variance": variance_info,
        "recent_transitions": transitions,
        "all_stages": [
            {"code": st, "title": STAGE_TITLES.get(st, st), "step": idx + 1}
            for idx, st in enumerate(LIFECYCLE_SEQUENCE)
        ]
    }

@LifecycleRouter.post("/{po_id}/transition")
def transition_order_stage(
    po_id: int,
    req: StageTransitionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context)
):
    """
    Advances or rolls back the procurement lifecycle stage with optimistic locking and RBAC.
    """
    if req.target_stage == "RFQ_SENT":
        if not can_access_sourcing(user, "Send_RFQ"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access forbidden: Permission 'Send_RFQ' is required to send RFQs to suppliers."
            )
    if req.target_stage in ["QUOTE_APPROVED", "PO_ISSUED"]:
        if not can_access_sourcing(user, "Approve_Quote"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access forbidden: Permission 'Approve_Quote' is required to approve quotes or issue purchase orders."
            )

    po = LifecycleService.transition_stage(
        po_id=po_id,
        target_stage=req.target_stage,
        expected_version=req.expected_version,
        user_id=getattr(user, "id", None),
        comment=req.comment,
        db=db
    )
    return {
        "message": f"Successfully transitioned to {po.lifecycle_stage}.",
        "po_id": po.id,
        "lifecycle_stage": po.lifecycle_stage,
        "lifecycle_version": po.lifecycle_version,
        "lifecycle_locked": po.lifecycle_locked
    }

@LifecycleRouter.get("/{po_id}/quotes/comparison")
def get_quote_comparison(
    po_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_sourcing_permission("Compare_Quote")),
    org_context: OrgContext = Depends(get_org_context)
):
    """
    Returns side-by-side comparison matrix of all vendor quotes with historical benchmarks.
    """
    return QuoteComparisonService.get_comparison_matrix(po_id, db)

@LifecycleRouter.post("/{po_id}/quotes")
def create_vendor_quote(
    po_id: int,
    req: VendorQuoteCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_sourcing_permission("Add_VendorQuote")),
    org_context: OrgContext = Depends(get_org_context)
):
    """
    Captures a vendor quotation against this PO.
    """
    po_query = db.query(PurchaseOrder).filter(PurchaseOrder.id == po_id, PurchaseOrder.is_deleted == False)
    po = apply_org_filter(po_query, PurchaseOrder, org_context).first()
    if not po:
        raise HTTPException(status_code=404, detail="Purchase Order not found.")

    supp = db.query(Supplier).filter(
        Supplier.supplier_id == req.supplier_id,
        Supplier.is_deleted != True,
        or_(Supplier.is_shared == True, Supplier.org_id == po.org_id),
    ).first()
    if not supp:
        raise HTTPException(status_code=404, detail="Supplier not found.")

    # Check if a quote from this supplier already exists on this PO
    existing_quote = db.query(VendorQuote).filter(
        VendorQuote.po_id == po.id,
        VendorQuote.supplier_id == req.supplier_id,
        VendorQuote.is_deleted == False
    ).first()
    if existing_quote:
        raise HTTPException(
            status_code=400,
            detail=f"A quotation from '{supp.name}' has already been recorded for this RFQ (Ref: {existing_quote.quote_reference or 'Quote #' + str(existing_quote.id)}). Please edit the existing quote instead of adding a duplicate."
        )

    # Calculate total quoted
    total_calc = sum(Decimal(str(it.quantity_quoted)) * Decimal(str(it.unit_price)) for it in req.items)

    quote = VendorQuote(
        po_id=po.id,
        supplier_id=req.supplier_id,
        quote_reference=req.quote_reference,
        quote_date=req.quote_date or date.today(),
        valid_until=req.valid_until,
        total_quoted_amount=total_calc,
        currency=req.currency or "USD",
        delivery_lead_time_days=req.delivery_lead_time_days,
        payment_terms=req.payment_terms,
        shipping_terms=req.shipping_terms,
        score_notes=req.score_notes,
        status="PENDING",
        org_id=po.org_id,
        created_by=getattr(user, "id", None)
    )
    db.add(quote)
    db.flush()

    for item_in in req.items:
        line_total = Decimal(str(item_in.quantity_quoted)) * Decimal(str(item_in.unit_price))
        qi = VendorQuoteItem(
            vendor_quote_id=quote.id,
            po_item_id=item_in.po_item_id,
            inventory_product_id=item_in.inventory_product_id,
            item_code=item_in.item_code,
            description=item_in.description,
            quantity_quoted=Decimal(str(item_in.quantity_quoted)),
            unit_price=Decimal(str(item_in.unit_price)),
            total_price=line_total,
            currency=req.currency or "USD",
            availability=item_in.availability or "AVAILABLE",
            lead_time_days=item_in.lead_time_days or req.delivery_lead_time_days,
            is_substitute=bool(item_in.is_substitute),
            notes=item_in.notes,
            created_by=getattr(user, "id", None)
        )
        db.add(qi)

    # Update milestone date on PO
    if not po.quote_received_date:
        po.quote_received_date = quote.quote_date or date.today()
    if not po.quote_sent_date:
        po.quote_sent_date = date.today()
    if not po.order_mail_date:
        po.order_mail_date = date.today()

    # If currently RFQ_SENT or CONFIRMED, auto-advance to QUOTE_RECEIVED
    if po.lifecycle_stage in ["RFQ_SENT", "CONFIRMED"]:
        po.lifecycle_stage = "QUOTE_RECEIVED"
        po.lifecycle_version += 1

    db.commit()
    db.refresh(quote)

    return {
        "message": "Vendor quote successfully recorded.",
        "quote_id": quote.id,
        "total_quoted_amount": float(quote.total_quoted_amount),
        "items_count": len(req.items)
    }

@LifecycleRouter.get("/{po_id}/quotes/{quote_id}")
def get_vendor_quote(
    po_id: int,
    quote_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_sourcing_permission("View_VendorQuote")),
    org_context: OrgContext = Depends(get_org_context)
):
    """
    Fetches full details of a specific vendor quotation including its line items.
    """
    quote = db.query(VendorQuote).filter(
        VendorQuote.id == quote_id,
        VendorQuote.po_id == po_id,
        VendorQuote.is_deleted == False
    ).first()
    if not quote:
        raise HTTPException(status_code=404, detail="Vendor quote not found.")

    return {
        "id": quote.id,
        "po_id": quote.po_id,
        "supplier_id": quote.supplier_id,
        "supplier_name": quote.supplier.name if quote.supplier else "",
        "quote_reference": quote.quote_reference,
        "quote_date": quote.quote_date.isoformat() if quote.quote_date else None,
        "valid_until": quote.valid_until.isoformat() if quote.valid_until else None,
        "total_quoted_amount": float(quote.total_quoted_amount or 0),
        "currency": quote.currency or "USD",
        "delivery_lead_time_days": quote.delivery_lead_time_days,
        "payment_terms": quote.payment_terms,
        "shipping_terms": quote.shipping_terms,
        "score_notes": quote.score_notes,
        "status": quote.status,
        "items": [{
            "id": qi.id,
            "po_item_id": qi.po_item_id,
            "inventory_product_id": qi.inventory_product_id,
            "item_code": qi.item_code,
            "description": qi.description,
            "quantity_quoted": float(qi.quantity_quoted or 0),
            "unit_price": float(qi.unit_price or 0),
            "total_price": float(qi.total_price or 0),
            "currency": qi.currency or quote.currency,
            "availability": qi.availability or "AVAILABLE",
            "lead_time_days": qi.lead_time_days,
            "is_substitute": qi.is_substitute or False,
            "notes": qi.notes or ""
        } for qi in (quote.items or []) if not qi.is_deleted]
    }

@LifecycleRouter.put("/{po_id}/quotes/{quote_id}")
def update_vendor_quote(
    po_id: int,
    quote_id: int,
    req: VendorQuoteUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_sourcing_permission("Add_VendorQuote")),
    org_context: OrgContext = Depends(get_org_context)
):
    """
    Updates an existing vendor quotation and its line item details.
    """
    po_query = db.query(PurchaseOrder).filter(PurchaseOrder.id == po_id, PurchaseOrder.is_deleted == False)
    po = apply_org_filter(po_query, PurchaseOrder, org_context).first()
    if not po:
        raise HTTPException(status_code=404, detail="Purchase Order not found.")

    quote = db.query(VendorQuote).filter(
        VendorQuote.id == quote_id,
        VendorQuote.po_id == po_id,
        VendorQuote.is_deleted == False
    ).first()
    if not quote:
        raise HTTPException(status_code=404, detail="Vendor quote not found.")

    if req.supplier_id is not None and req.supplier_id != quote.supplier_id:
        supp = db.query(Supplier).filter(
            Supplier.supplier_id == req.supplier_id,
            Supplier.is_deleted != True,
            or_(Supplier.is_shared == True, Supplier.org_id == po.org_id),
        ).first()
        if not supp:
            raise HTTPException(status_code=404, detail="Supplier not found.")
        duplicate_check = db.query(VendorQuote).filter(
            VendorQuote.po_id == po.id,
            VendorQuote.supplier_id == req.supplier_id,
            VendorQuote.id != quote.id,
            VendorQuote.is_deleted == False
        ).first()
        if duplicate_check:
            raise HTTPException(
                status_code=400,
                detail=f"A quotation from '{supp.name}' already exists for this RFQ."
            )
        quote.supplier_id = req.supplier_id

    if req.quote_reference is not None:
        quote.quote_reference = req.quote_reference
    if req.quote_date is not None:
        quote.quote_date = req.quote_date
    if req.valid_until is not None:
        quote.valid_until = req.valid_until
    if req.delivery_lead_time_days is not None:
        quote.delivery_lead_time_days = req.delivery_lead_time_days
    if req.payment_terms is not None:
        quote.payment_terms = req.payment_terms
    if req.shipping_terms is not None:
        quote.shipping_terms = req.shipping_terms
    if req.score_notes is not None:
        quote.score_notes = req.score_notes
    if req.currency is not None:
        quote.currency = req.currency

    quote.updated_by = getattr(user, "id", None)

    # Update line items if provided
    if req.items is not None:
        existing_items = {qi.po_item_id: qi for qi in (quote.items or []) if not qi.is_deleted and qi.po_item_id}
        incoming_po_item_ids = {it.po_item_id for it in req.items if it.po_item_id}
        total_calc = Decimal("0.00")

        # Soft-delete items that are omitted in incoming update
        for po_item_id, qi in existing_items.items():
            if po_item_id not in incoming_po_item_ids:
                qi.is_deleted = True
                qi.updated_by = getattr(user, "id", None)

        for item_in in req.items:
            line_total = Decimal(str(item_in.quantity_quoted)) * Decimal(str(item_in.unit_price))
            total_calc += line_total

            qi = existing_items.get(item_in.po_item_id) if item_in.po_item_id else None
            if qi:
                qi.quantity_quoted = Decimal(str(item_in.quantity_quoted))
                qi.unit_price = Decimal(str(item_in.unit_price))
                qi.total_price = line_total
                qi.currency = quote.currency
                qi.availability = item_in.availability or "AVAILABLE"
                qi.lead_time_days = item_in.lead_time_days or quote.delivery_lead_time_days
                qi.is_substitute = bool(item_in.is_substitute)
                qi.notes = item_in.notes
                qi.is_deleted = False
                qi.updated_by = getattr(user, "id", None)
            else:
                new_qi = VendorQuoteItem(
                    vendor_quote_id=quote.id,
                    po_item_id=item_in.po_item_id,
                    inventory_product_id=item_in.inventory_product_id,
                    item_code=item_in.item_code,
                    description=item_in.description,
                    quantity_quoted=Decimal(str(item_in.quantity_quoted)),
                    unit_price=Decimal(str(item_in.unit_price)),
                    total_price=line_total,
                    currency=quote.currency,
                    availability=item_in.availability or "AVAILABLE",
                    lead_time_days=item_in.lead_time_days or quote.delivery_lead_time_days,
                    is_substitute=bool(item_in.is_substitute),
                    notes=item_in.notes,
                    created_by=getattr(user, "id", None)
                )
                db.add(new_qi)

        quote.total_quoted_amount = total_calc

        # If this quote was already awarded to the PO, synchronize PO item prices
        if po.selected_quote_id == quote.id:
            for item_in in req.items:
                if item_in.po_item_id:
                    po_it = db.query(POItem).filter(POItem.id == item_in.po_item_id, POItem.is_deleted == False).first()
                    if po_it:
                        po_it.unit_price = Decimal(str(item_in.unit_price))
                        po_it.total_price = Decimal(str(po_it.quantity_ordered or 0)) * Decimal(str(item_in.unit_price))

    db.commit()
    db.refresh(quote)

    return {
        "message": "Vendor quote successfully updated.",
        "quote_id": quote.id,
        "total_quoted_amount": float(quote.total_quoted_amount)
    }

@LifecycleRouter.delete("/{po_id}/quotes/{quote_id}")
def delete_vendor_quote(
    po_id: int,
    quote_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_sourcing_permission("Add_VendorQuote")),
    org_context: OrgContext = Depends(get_org_context)
):
    """
    Soft-deletes a vendor quotation and adjusts PO selection state if needed.
    """
    po = db.query(PurchaseOrder).filter(PurchaseOrder.id == po_id, PurchaseOrder.is_deleted == False).first()
    if not po:
        raise HTTPException(status_code=404, detail="Purchase Order not found.")

    quote = db.query(VendorQuote).filter(
        VendorQuote.id == quote_id,
        VendorQuote.po_id == po_id,
        VendorQuote.is_deleted == False
    ).first()
    if not quote:
        raise HTTPException(status_code=404, detail="Vendor quote not found.")

    # Soft delete the quote and its items
    quote.is_deleted = True
    quote.updated_by = getattr(user, "id", None)
    for qi in (quote.items or []):
        qi.is_deleted = True
        qi.updated_by = getattr(user, "id", None)

    # If this quote was selected / awarded
    if po.selected_quote_id == quote.id:
        po.selected_quote_id = None
        if po.lifecycle_stage == "QUOTE_APPROVED":
            po.lifecycle_stage = "QUOTE_RECEIVED"
            po.lifecycle_version += 1

    # Check remaining active quotes for this PO
    remaining_count = db.query(VendorQuote).filter(
        VendorQuote.po_id == po.id,
        VendorQuote.is_deleted == False,
        VendorQuote.id != quote.id
    ).count()

    if remaining_count == 0:
        po.lifecycle_stage = "RFQ_SENT"
        po.lifecycle_version += 1

    db.commit()

    return {
        "message": "Vendor quote successfully deleted.",
        "quote_id": quote_id,
        "remaining_quotes": remaining_count
    }

@LifecycleRouter.post("/{po_id}/quotes/{quote_id}/award")
def award_quote_to_po(
    po_id: int,
    quote_id: int,
    req: Optional[QuoteAwardRequest] = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_sourcing_permission("Approve_Quote")),
    org_context: OrgContext = Depends(get_org_context)
):
    """
    Awards a winning vendor quote, applies approved prices to PO line items,
    and advances lifecycle stage to QUOTE_APPROVED.
    """
    line_awards = req.line_awards if req else None
    return QuoteComparisonService.award_quote(
        po_id=po_id,
        quote_id=quote_id,
        line_awards=line_awards,
        user_id=getattr(user, "id", None),
        db=db
    )

@LifecycleRouter.post("/{po_id}/quotes/split-award")
def split_award_quotes_endpoint(
    po_id: int,
    req: SplitAwardRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_sourcing_permission("Approve_Quote")),
    org_context: OrgContext = Depends(get_org_context)
):
    """
    Awards RFQ line items across one or multiple vendor quotes, atomically generates child POs,
    and advances RFQ to QUOTE_APPROVED / AWARDED.
    """
    alloc_dicts = [a.model_dump() if hasattr(a, 'model_dump') else a.dict() for a in req.allocations]
    return QuoteComparisonService.split_award_rfq(
        rfq_id=po_id,
        allocations=alloc_dicts,
        user_id=getattr(user, "id", None),
        db=db
    )

@LifecycleRouter.post("/{po_id}/quotes/revoke-award")
def revoke_award_endpoint(
    po_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_sourcing_permission("Approve_Quote")),
    org_context: OrgContext = Depends(get_org_context)
):
    """
    Safely revokes an existing award/split, cancelling draft child POs and returning RFQ to QUOTE_RECEIVED.
    """
    return QuoteComparisonService.revoke_rfq_award(
        rfq_id=po_id,
        user_id=getattr(user, "id", None),
        db=db
    )


@LifecycleRouter.get("/{po_id}/items/{item_id}/history")
def get_item_revision_history(
    po_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context)
):
    """
    Returns the complete delta revision timeline for a specific line item.
    """
    item = db.query(POItem).filter(POItem.id == item_id, POItem.po_id == po_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Line item not found.")

    history_entries = db.query(POItemHistory).filter(
        POItemHistory.po_item_id == item_id
    ).order_by(POItemHistory.created_at.desc()).all()

    return {
        "item_id": item.id,
        "item_code": item.item_code,
        "description": item.description,
        "current_quantity": float(item.quantity_ordered or 0),
        "current_unit_price": float(item.unit_price) if item.unit_price else None,
        "current_status": item.item_status,
        "revisions": [
            {
                "id": h.id,
                "lifecycle_stage": h.lifecycle_stage,
                "lifecycle_version": h.lifecycle_version,
                "action": h.action,
                "field_name": h.field_name,
                "old_value": h.old_value,
                "new_value": h.new_value,
                "quantity": float(h.quantity) if h.quantity else None,
                "unit_price": float(h.unit_price) if h.unit_price else None,
                "total_price": float(h.total_price) if h.total_price else None,
                "reason": h.reason,
                "created_at": h.created_at.isoformat() if h.created_at else None,
                "created_by": h.created_by
            }
            for h in history_entries
        ]
    }

@LifecycleRouter.post("/{po_id}/approve-variance")
def approve_proforma_variance(
    po_id: int,
    req: VarianceApprovalRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context)
):
    """
    Unlocks a PO blocked by price variance. Gated by Approve_Variance permission.
    """
    check_variance_permission(user, org_context)
    po = LifecycleService.approve_variance(
        po_id=po_id,
        user_id=getattr(user, "id", None),
        justification=req.justification,
        db=db
    )
    return {
        "message": "Price variance approved and PO unlocked.",
        "po_id": po.id,
        "lifecycle_locked": po.lifecycle_locked,
        "lifecycle_version": po.lifecycle_version
    }

# ── Version History & Snapshot Endpoints ─────────────────────────────────────

@LifecycleRouter.get("/{po_id}/versions")
def get_order_versions(
    po_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context)
):
    """
    Returns full chronological version history with stage-scoped versions and transition lineage.
    """
    po = db.query(PurchaseOrder).filter(PurchaseOrder.id == po_id, PurchaseOrder.is_deleted == False).first()
    if not po:
        raise HTTPException(status_code=404, detail="Purchase Order not found")

    snapshots = (
        db.query(POVersionSnapshot)
        .filter(POVersionSnapshot.po_id == po_id, POVersionSnapshot.is_deleted == False)
        .order_by(POVersionSnapshot.id.desc())
        .all()
    )

    result = []
    for s in snapshots:
        creator_name = None
        if s.created_by_user:
            creator_name = getattr(s.created_by_user, "fullname", None) or getattr(s.created_by_user, "username", None)

        result.append({
            "id": s.id,
            "po_id": s.po_id,
            "lifecycle_stage": s.lifecycle_stage,
            "stage_version": s.stage_version,
            "global_version": s.global_version,
            "parent_snapshot_id": s.parent_snapshot_id,
            "transition_type": s.transition_type,
            "change_summary": s.change_summary,
            "diff_data": s.diff_data or {},
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "created_by": s.created_by,
            "created_by_name": creator_name
        })

    return {
        "po_id": po.id,
        "po_number": po.po_number,
        "current_stage": po.lifecycle_stage or "DRAFT",
        "current_stage_version": getattr(po, "stage_version", 1) or 1,
        "current_global_version": po.lifecycle_version or 1,
        "versions": result
    }

@LifecycleRouter.get("/{po_id}/versions/{version_id}")
def get_order_version_detail(
    po_id: int,
    version_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context)
):
    """
    Returns full immutable snapshot payload for time-travel viewing.
    """
    snapshot = (
        db.query(POVersionSnapshot)
        .filter(
            POVersionSnapshot.id == version_id,
            POVersionSnapshot.po_id == po_id,
            POVersionSnapshot.is_deleted == False
        )
        .first()
    )
    if not snapshot:
        raise HTTPException(status_code=404, detail="Version snapshot not found")

    creator_name = None
    if snapshot.created_by_user:
        creator_name = getattr(snapshot.created_by_user, "fullname", None) or getattr(snapshot.created_by_user, "username", None)

    return {
        "id": snapshot.id,
        "po_id": snapshot.po_id,
        "lifecycle_stage": snapshot.lifecycle_stage,
        "stage_version": snapshot.stage_version,
        "global_version": snapshot.global_version,
        "parent_snapshot_id": snapshot.parent_snapshot_id,
        "transition_type": snapshot.transition_type,
        "change_summary": snapshot.change_summary,
        "diff_data": snapshot.diff_data or {},
        "snapshot_data": snapshot.snapshot_data,
        "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
        "created_by": snapshot.created_by,
        "created_by_name": creator_name
    }

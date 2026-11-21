"""Proforma invoices: the vendor's document, and the thing payments are made against.

The PO is the commitment and carries no money. A proforma is recorded against
an issued PO, compared with the PO's lines, approved (with Approve_Variance
when it differs beyond the supplier's tolerance), and every payment is then
recorded on it. Changing an approved proforma asks for a reason first, as
every other revision in procurement does.
"""
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload, selectinload

from Model.db import get_db
from Model.containermgmt.Orders.OrderPayment import OrderPayment
from Model.containermgmt.Orders.POItem import POItem
from Model.containermgmt.Orders.ProformaInvoice import ProformaInvoice, ProformaInvoiceItem
from Model.containermgmt.Orders.PurchaseOrder import PurchaseOrder
from Model.Credentials.users import User
from auth.dependencies import get_current_user, get_org_context
from auth.security_guards import has_permission, is_financial_user
from Services.proforma_service import (
    OPEN_STATUSES, PAYABLE_STATUSES, TOLERANCE, evaluate_variance, next_proforma_number,
    paid_on, price_unpriced_po_lines, revision_entry, sync_payment_state,
)
from Utils.org_filter import OrgContext, apply_org_filter

logger = logging.getLogger("containerMgmt.proforma")

ProformaRouter = APIRouter(prefix="/proformas", tags=["Proforma Invoices"])

# A proforma can only be raised against an order that has been issued.
ISSUED_STAGES = ("PO_ISSUED", "PROFORMA")
MIN_REASON = 5


def _f(value) -> float:
    return float(value) if value is not None else 0.0


def _require_financial(user: User, org_context: OrgContext) -> None:
    if not is_financial_user(user, org_context):
        raise HTTPException(status_code=403, detail="Only Accounts/Finance users can see or change proforma invoices.")


def _require(user: User, permission: str) -> None:
    if not has_permission(user, permission):
        raise HTTPException(status_code=403, detail=f"Operation forbidden: Missing required permission '{permission}'.")


def _reason(payload: dict) -> str:
    reason = (payload.get("reason") or "").strip()
    if len(reason) < MIN_REASON:
        raise HTTPException(status_code=422, detail="A reason of at least 5 characters is required.")
    return reason


def _date(value) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=422, detail=f"'{value}' is not a valid date (use YYYY-MM-DD).")


def _dec(value, field: str) -> Decimal:
    try:
        return Decimal(str(value if value not in (None, "") else 0))
    except Exception:
        raise HTTPException(status_code=422, detail=f"'{field}' must be a number.")


def _load(db: Session, proforma_id: int, org_context: OrgContext) -> ProformaInvoice:
    query = db.query(ProformaInvoice).options(
        selectinload(ProformaInvoice.items),
        joinedload(ProformaInvoice.purchase_order),
    ).filter(ProformaInvoice.id == proforma_id, ProformaInvoice.is_deleted == False)  # noqa: E712
    pf = apply_org_filter(query, ProformaInvoice, org_context).first()
    if not pf:
        raise HTTPException(status_code=404, detail="Proforma invoice not found")
    return pf


def _load_po(db: Session, po_id: int, org_context: OrgContext) -> PurchaseOrder:
    query = db.query(PurchaseOrder).options(selectinload(PurchaseOrder.items), selectinload(PurchaseOrder.proformas)).filter(
        PurchaseOrder.id == po_id, PurchaseOrder.is_deleted == False  # noqa: E712
    )
    po = apply_org_filter(query, PurchaseOrder, org_context).first()
    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    return po


def _item_to_dict(it: ProformaInvoiceItem) -> Dict[str, Any]:
    return {
        "id": it.id,
        "po_item_id": it.po_item_id,
        "item_code": it.item_code,
        "description": it.description,
        "quantity": _f(it.quantity),
        "unit": it.unit,
        "unit_price": _f(it.unit_price),
        "total_price": _f(it.total_price),
        "po_unit_price": _f(it.po_unit_price) if it.po_unit_price is not None else None,
        "variance_pct": _f(it.variance_pct) if it.variance_pct is not None else None,
    }


def _payment_to_dict(pm: OrderPayment) -> Dict[str, Any]:
    return {
        "id": pm.id,
        "payment_type": pm.payment_type,
        "amount": _f(pm.amount),
        "currency": pm.currency,
        "paid_date": pm.paid_date.isoformat() if pm.paid_date else None,
        "payment_method": pm.payment_method,
        "reference_number": pm.reference_number,
        "notes": pm.notes,
        "status": pm.status,
        "evidence_doc_id": str(pm.evidence_doc_id) if pm.evidence_doc_id else None,
    }


def proforma_to_dict(pf: ProformaInvoice, db: Session, with_items: bool = True, with_payments: bool = False) -> Dict[str, Any]:
    paid = paid_on(db, pf.id)
    total = _f(pf.total_amount)
    po = pf.purchase_order
    data = {
        "id": pf.id,
        "proforma_number": pf.proforma_number,
        "vendor_proforma_number": pf.vendor_proforma_number,
        "vendor_proforma_date": pf.vendor_proforma_date.isoformat() if pf.vendor_proforma_date else None,
        "valid_until": pf.valid_until.isoformat() if pf.valid_until else None,
        "po_id": pf.po_id,
        "po_number": po.po_number if po else None,
        "org_id": pf.org_id,
        "supplier_id": pf.supplier_id,
        "supplier_name": pf.supplier_name_at_issue,
        "currency": pf.currency,
        "total_amount": total,
        "amount_paid": paid,
        "balance_due": max(0.0, total - paid),
        "advance_percent": _f(pf.advance_percent) if pf.advance_percent is not None else None,
        "advance_due": round(total * _f(pf.advance_percent) / 100.0, 2) if pf.advance_percent is not None else None,
        "payment_terms": pf.payment_terms,
        "bank_details": pf.bank_details,
        "status": pf.status,
        "source": pf.source,
        "supersedes_id": pf.supersedes_id,
        "variance_status": pf.variance_status,
        "variance_data": pf.variance_data,
        "variance_justification": pf.variance_justification,
        "approved_at": pf.approved_at.isoformat() if pf.approved_at else None,
        "notes": pf.notes,
        "revision_count": pf.revision_count or 0,
        "revisions": pf.revisions or [],
        "created_at": pf.created_at.isoformat() if getattr(pf, "created_at", None) else None,
    }
    if with_items:
        data["items"] = [_item_to_dict(i) for i in pf.items if not i.is_deleted]
    if with_payments:
        rows = db.query(OrderPayment).filter(
            OrderPayment.proforma_id == pf.id, OrderPayment.is_deleted == False  # noqa: E712
        ).order_by(OrderPayment.id.desc()).all()
        data["payments"] = [_payment_to_dict(p) for p in rows]
    return data


def _build_lines(po: PurchaseOrder, raw_items: List[dict], db: Session) -> List[Dict[str, Any]]:
    """Validate the typed lines, tie them to PO lines and score them against the PO."""
    if not raw_items:
        raise HTTPException(status_code=422, detail="A proforma invoice needs at least one line.")
    po_item_ids = {it.id for it in po.items if not it.is_deleted}
    lines: List[Dict[str, Any]] = []
    for raw in raw_items:
        po_item_id = raw.get("po_item_id")
        if po_item_id is not None and int(po_item_id) not in po_item_ids:
            raise HTTPException(status_code=422, detail=f"Line {po_item_id} does not belong to this purchase order.")
        qty = _dec(raw.get("quantity"), "quantity")
        price = _dec(raw.get("unit_price"), "unit_price")
        if qty <= 0:
            raise HTTPException(status_code=422, detail="Quantity must be greater than zero.")
        if price <= 0:
            raise HTTPException(status_code=422, detail="Unit price must be greater than zero.")
        description = (raw.get("description") or "").strip()
        if not description and po_item_id is not None:
            description = next((i.description for i in po.items if i.id == int(po_item_id)), "")
        if not description:
            raise HTTPException(status_code=422, detail="Every line needs a description.")
        lines.append({
            "po_item_id": int(po_item_id) if po_item_id is not None else None,
            "item_code": raw.get("item_code"),
            "description": description,
            "quantity": qty,
            "unit": raw.get("unit") or "PCS",
            "unit_price": price,
            "total_price": (qty * price).quantize(Decimal("0.01")),
        })
    return lines


def _write_lines(pf: ProformaInvoice, po: PurchaseOrder, lines: List[Dict[str, Any]], user_id: Optional[int]) -> Decimal:
    for existing in list(pf.items):
        pf.items.remove(existing)
    total = Decimal("0")
    for ln in lines:
        pf.items.append(ProformaInvoiceItem(
            org_id=po.org_id,
            po_item_id=ln["po_item_id"],
            item_code=ln.get("item_code"),
            description=ln["description"],
            quantity=ln["quantity"],
            unit=ln["unit"],
            unit_price=ln["unit_price"],
            total_price=ln["total_price"],
            po_unit_price=ln.get("po_unit_price"),
            variance_pct=ln.get("variance_pct"),
            created_by=user_id,
        ))
        total += ln["total_price"]
    return total


def _apply_header(pf: ProformaInvoice, payload: dict) -> None:
    if "vendor_proforma_number" in payload:
        pf.vendor_proforma_number = (payload.get("vendor_proforma_number") or "").strip() or None
    if "vendor_proforma_date" in payload:
        pf.vendor_proforma_date = _date(payload.get("vendor_proforma_date"))
    if "valid_until" in payload:
        pf.valid_until = _date(payload.get("valid_until"))
    if "currency" in payload and payload.get("currency"):
        pf.currency = str(payload["currency"]).strip().upper()[:10]
    if "payment_terms" in payload:
        pf.payment_terms = (payload.get("payment_terms") or "").strip() or None
    if "advance_percent" in payload:
        raw = payload.get("advance_percent")
        if raw in (None, ""):
            pf.advance_percent = None
        else:
            pct = _dec(raw, "advance_percent")
            if pct < 0 or pct > 100:
                raise HTTPException(status_code=422, detail="Advance percentage must be between 0 and 100.")
            pf.advance_percent = pct
    if "bank_details" in payload:
        details = payload.get("bank_details")
        pf.bank_details = details if isinstance(details, (dict, list)) else None
    if "notes" in payload:
        pf.notes = payload.get("notes")


# ── Register ──────────────────────────────────────────────────────────────────
@ProformaRouter.get("")
@ProformaRouter.get("/")
def list_proformas(
    po_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    unpaid_only: bool = Query(False),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    user: User = Depends(get_current_user),
):
    _require_financial(user, org_context)
    query = db.query(ProformaInvoice).options(joinedload(ProformaInvoice.purchase_order)).filter(
        ProformaInvoice.is_deleted == False  # noqa: E712
    )
    query = apply_org_filter(query, ProformaInvoice, org_context)
    if po_id:
        query = query.filter(ProformaInvoice.po_id == po_id)
    if status:
        query = query.filter(ProformaInvoice.status.in_([s.strip().upper() for s in status.split(",") if s.strip()]))
    if unpaid_only:
        query = query.filter(ProformaInvoice.status.in_(("APPROVED", "PART_PAID")))
    if search:
        like = f"%{search.strip()}%"
        query = query.filter(or_(
            ProformaInvoice.proforma_number.ilike(like),
            ProformaInvoice.vendor_proforma_number.ilike(like),
            ProformaInvoice.supplier_name_at_issue.ilike(like),
        ))
    total = query.count()
    rows = query.order_by(ProformaInvoice.id.desc()).offset((page - 1) * limit).limit(limit).all()
    return {
        "items": [proforma_to_dict(pf, db, with_items=False) for pf in rows],
        "total": total, "page": page, "limit": limit,
    }


@ProformaRouter.get("/{proforma_id}")
def get_proforma(
    proforma_id: int,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    user: User = Depends(get_current_user),
):
    _require_financial(user, org_context)
    pf = _load(db, proforma_id, org_context)
    return proforma_to_dict(pf, db, with_payments=True)


# ── Record ────────────────────────────────────────────────────────────────────
@ProformaRouter.post("")
@ProformaRouter.post("/")
def record_proforma(
    payload: dict,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    user: User = Depends(get_current_user),
):
    _require_financial(user, org_context)
    _require(user, "Record_Proforma")
    if not payload.get("po_id"):
        raise HTTPException(status_code=422, detail="po_id is required.")
    po = _load_po(db, int(payload["po_id"]), org_context)
    if (po.doc_type or "").upper() != "PO":
        raise HTTPException(status_code=400, detail="A proforma invoice is recorded against a purchase order, not an RFQ.")
    if po.lifecycle_stage not in ISSUED_STAGES:
        raise HTTPException(status_code=409, detail="The purchase order must be issued before a proforma invoice is recorded.")

    superseded = None
    if payload.get("supersedes_id"):
        superseded = next((p for p in po.proformas if p.id == int(payload["supersedes_id"]) and not p.is_deleted), None)
        if superseded is None:
            raise HTTPException(status_code=404, detail="The proforma to replace was not found on this purchase order.")
        if paid_on(db, superseded.id) > TOLERANCE:
            raise HTTPException(
                status_code=409,
                detail="That proforma already has payments. Revise it with a reason instead of replacing it.",
            )

    lines = _build_lines(po, payload.get("items") or [], db)
    variance = evaluate_variance(po, lines, db)

    pf = ProformaInvoice(
        org_id=po.org_id,
        proforma_number=next_proforma_number(db, po),
        po_id=po.id,
        supplier_id=po.supplier_id,
        supplier_name_at_issue=po.supplier_name_at_issue or po.company,
        currency=po.currency or "USD",
        status="RECEIVED",
        source="VENDOR",
        supersedes_id=superseded.id if superseded else None,
        variance_status=variance["status"],
        variance_data=variance,
        created_by=user.id,
    )
    _apply_header(pf, payload)
    db.add(pf)
    db.flush()
    pf.total_amount = _write_lines(pf, po, lines, user.id)

    if superseded is not None:
        superseded.status = "SUPERSEDED"
        superseded.updated_by = user.id

    sync_payment_state(db, po)
    db.commit()
    db.refresh(pf)
    return proforma_to_dict(pf, db, with_payments=True)


# ── Edit / revise ─────────────────────────────────────────────────────────────
@ProformaRouter.put("/{proforma_id}")
def update_proforma(
    proforma_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    user: User = Depends(get_current_user),
):
    """Edit a proforma. Before approval it is edited freely; after it, a reason comes first."""
    _require_financial(user, org_context)
    pf = _load(db, proforma_id, org_context)
    if pf.status in ("CANCELLED", "SUPERSEDED"):
        raise HTTPException(status_code=409, detail=f"A {pf.status.lower()} proforma cannot be changed.")
    po = _load_po(db, pf.po_id, org_context)

    revising = pf.status in PAYABLE_STATUSES
    if revising:
        _require(user, "Revise_Proforma")
        reason = _reason(payload)
    else:
        _require(user, "Record_Proforma")
        reason = None

    paid = paid_on(db, pf.id)
    changed: List[str] = []
    before_total = _f(pf.total_amount)

    _apply_header(pf, payload)
    if payload.get("items") is not None:
        lines = _build_lines(po, payload["items"], db)
        variance = evaluate_variance(po, lines, db)
        new_total = _write_lines(pf, po, lines, user.id)
        if paid > TOLERANCE and float(new_total) < paid - TOLERANCE:
            raise HTTPException(
                status_code=409,
                detail=f"The new total ({float(new_total):.2f}) is below what has already been paid ({paid:.2f}).",
            )
        pf.total_amount = new_total
        pf.variance_status = variance["status"]
        pf.variance_data = variance
        pf.variance_justification = None
        if float(new_total) != before_total:
            changed.append(f"total {before_total:.2f} to {float(new_total):.2f}")
        else:
            changed.append("lines")
        if revising and paid <= TOLERANCE:
            # Nothing was paid, so the changed document goes back for approval.
            pf.status = "RECEIVED"
    if revising:
        history = list(pf.revisions or [])
        history.append(revision_entry(user.id, reason, ", ".join(changed) or "header details"))
        pf.revisions = history
        pf.revision_count = (pf.revision_count or 0) + 1
    pf.updated_by = user.id

    sync_payment_state(db, po)
    db.commit()
    db.refresh(pf)
    return proforma_to_dict(pf, db, with_payments=True)


# ── Approve ───────────────────────────────────────────────────────────────────
@ProformaRouter.post("/{proforma_id}/approve")
def approve_proforma(
    proforma_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    user: User = Depends(get_current_user),
):
    _require_financial(user, org_context)
    _require(user, "Approve_Proforma")
    pf = _load(db, proforma_id, org_context)
    if pf.status != "RECEIVED":
        raise HTTPException(status_code=409, detail=f"Only a received proforma can be approved (this one is {pf.status}).")
    po = _load_po(db, pf.po_id, org_context)

    if pf.variance_status == "EXCEEDED":
        _require(user, "Approve_Variance")
        justification = (payload.get("justification") or "").strip()
        if len(justification) < MIN_REASON:
            raise HTTPException(
                status_code=422,
                detail="This proforma differs from the PO beyond tolerance. A justification of at least 5 characters is required.",
            )
        pf.variance_justification = justification
        pf.variance_status = "APPROVED"

    pf.status = "APPROVED"
    pf.approved_by = user.id
    pf.approved_at = date.today()
    pf.updated_by = user.id
    if not po.pi_confirmed_date:
        po.pi_confirmed_date = date.today()
    price_unpriced_po_lines(db, po, pf, user.id)

    sync_payment_state(db, po)
    db.commit()
    db.refresh(pf)
    return proforma_to_dict(pf, db, with_payments=True)


@ProformaRouter.post("/{proforma_id}/cancel")
def cancel_proforma(
    proforma_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    user: User = Depends(get_current_user),
):
    _require_financial(user, org_context)
    _require(user, "Revise_Proforma")
    reason = _reason(payload)
    pf = _load(db, proforma_id, org_context)
    if pf.status in ("CANCELLED", "SUPERSEDED"):
        raise HTTPException(status_code=409, detail=f"This proforma is already {pf.status.lower()}.")
    if paid_on(db, pf.id) > TOLERANCE:
        raise HTTPException(status_code=409, detail="This proforma has payments. Refund them first.")
    po = _load_po(db, pf.po_id, org_context)

    history = list(pf.revisions or [])
    history.append(revision_entry(user.id, reason, "cancelled"))
    pf.revisions = history
    pf.revision_count = (pf.revision_count or 0) + 1
    pf.status = "CANCELLED"
    pf.updated_by = user.id

    sync_payment_state(db, po)
    db.commit()
    db.refresh(pf)
    return proforma_to_dict(pf, db, with_payments=True)


# ── Payments ──────────────────────────────────────────────────────────────────
@ProformaRouter.post("/{proforma_id}/payments")
def record_proforma_payment(
    proforma_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    user: User = Depends(get_current_user),
):
    _require_financial(user, org_context)
    _require(user, "Add_Payment")
    pf = _load(db, proforma_id, org_context)
    if pf.status not in PAYABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"Payments are recorded on an approved proforma (this one is {pf.status}).",
        )
    po = _load_po(db, pf.po_id, org_context)

    raw_amt = float(payload.get("amount") or 0)
    p_type = (payload.get("payment_type") or "ADVANCE").strip().upper()
    paid = paid_on(db, pf.id)
    total = _f(pf.total_amount)

    if p_type == "RETURN":
        if raw_amt == 0:
            raise HTTPException(status_code=400, detail="Return payment amount cannot be zero.")
        amt = -abs(raw_amt)
        if abs(amt) > paid + TOLERANCE:
            raise HTTPException(
                status_code=400,
                detail=f"Return payment ({abs(amt):.2f}) cannot exceed what has been paid on this proforma ({paid:.2f}).",
            )
    else:
        if raw_amt <= 0:
            raise HTTPException(status_code=400, detail="Payment amount must be greater than zero.")
        amt = raw_amt
        remaining = max(0.0, total - paid)
        if total > 0 and amt > remaining + TOLERANCE and not bool(payload.get("allow_overpayment", False)):
            raise HTTPException(
                status_code=400,
                detail=f"Payment amount ({amt:.2f}) exceeds the amount still due on this proforma ({remaining:.2f}). "
                       "Overpayment is restricted without explicit authorization.",
            )

    paid_d = _date(payload.get("paid_date")) or date.today()
    payment = OrderPayment(
        org_id=po.org_id,
        po_id=po.id,
        proforma_id=pf.id,
        payment_type=p_type,
        amount=amt,
        currency=payload.get("currency") or pf.currency or po.currency or "USD",
        paid_date=paid_d,
        status="RETURNED" if p_type == "RETURN" else "PAID",
        payment_method=payload.get("payment_method"),
        reference_number=payload.get("reference_number"),
        notes=payload.get("notes"),
        created_by=user.id,
    )
    db.add(payment)
    db.flush()

    sync_payment_state(db, po)
    db.commit()
    db.refresh(pf)
    po_payments = db.query(OrderPayment).filter(
        OrderPayment.po_id == po.id, OrderPayment.is_deleted == False  # noqa: E712
    ).order_by(OrderPayment.id.desc()).all()
    return {
        "success": True,
        "message": f"Payment of {amt:.2f} recorded on {pf.proforma_number}",
        "advance_amount": _f(po.advance_amount),
        "balance_amount": _f(po.balance_amount),
        "payment_status": po.payment_status,
        "payments": [_payment_to_dict(p) for p in po_payments],
        "payment": _payment_to_dict(payment),
        "proforma": proforma_to_dict(pf, db, with_payments=True),
        "po": {
            "id": po.id,
            "advance_amount": _f(po.advance_amount),
            "balance_amount": _f(po.balance_amount),
            "payment_status": po.payment_status,
        },
    }

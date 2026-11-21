"""Convert a confirmed RFQ straight into a purchase order.

From Vendor Quotes & Bidding a confirmed RFQ has two ways forward: send it to
vendors for quotes, or convert it to a PO here. Converting takes the vendor (and
the quantity, if it has to change) and issues the PO at once, with no prices:
they come on the vendor's proforma, as
a child of the RFQ exactly like an award does, so the RFQ shows as awarded and
every guard that protects an awarded RFQ applies. The vendor comes from the
RFQ's template when it has one; otherwise the buyer chooses it. The PO then
goes on to a proforma like any other.
"""
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload

from Model.db import get_db
from Model.containermgmt.Orders.POItem import POItem
from Model.containermgmt.Orders.POStageTransition import POStageTransition
from Model.containermgmt.Orders.PurchaseOrder import PurchaseOrder
from Model.Credentials.users import User
from auth.dependencies import get_current_user, get_org_context
from auth.security_guards import can_access_sourcing
from Services.document_number_service import next_document_number
from Services.rfq_conversion_service import (
    ADJUST_REASONS, MIN_NOTE, active_lines, learn_vendor_terms, load_supplier, load_template, vendor_terms,
)
from Utils.org_filter import OrgContext, apply_org_filter
from .LifecycleService import LifecycleService

logger = logging.getLogger("containerMgmt.rfq_conversion")

RfqConversionRouter = APIRouter(prefix="/orders", tags=["RFQ to PO"])


def _authorise(user: User) -> None:
    # Converting replaces both the approval of a price and the issue of the PO.
    for permission in ("Approve_Quote", "Issue_PO"):
        if not can_access_sourcing(user, permission):
            raise HTTPException(
                status_code=403,
                detail=f"Access forbidden: Permission '{permission}' is required to convert an RFQ to a purchase order.",
            )


def _dec(value, field: str) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        raise HTTPException(status_code=422, detail=f"'{field}' must be a number.")


def _load_rfq(db: Session, rfq_id: int, org_context: OrgContext, lock: bool = False) -> PurchaseOrder:
    query = db.query(PurchaseOrder).options(selectinload(PurchaseOrder.items)).filter(
        PurchaseOrder.id == rfq_id, PurchaseOrder.is_deleted == False  # noqa: E712
    )
    query = apply_org_filter(query, PurchaseOrder, org_context)
    if lock:
        query = query.with_for_update(of=PurchaseOrder)
    rfq = query.first()
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ not found")
    if (rfq.doc_type or "").upper() != "RFQ":
        raise HTTPException(status_code=400, detail="Only an RFQ can be converted to a purchase order.")
    if rfq.lifecycle_stage != "CONFIRMED":
        raise HTTPException(
            status_code=409,
            detail=f"An RFQ is converted to a PO once it is confirmed and before it is sent (this one is {rfq.lifecycle_stage}). "
                   "Revise a sent RFQ first if it should be converted instead.",
        )
    return rfq


def _assert_not_converted(db: Session, rfq: PurchaseOrder) -> None:
    children = db.query(PurchaseOrder).filter(
        PurchaseOrder.parent_rfq_id == rfq.id, PurchaseOrder.is_deleted == False  # noqa: E712
    ).all()
    if children:
        raise HTTPException(
            status_code=409,
            detail="This RFQ already has Purchase Order(s): " + ", ".join(c.po_number for c in children) + ".",
        )


def _eta(value) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=422, detail=f"'{value}' is not a valid date (use YYYY-MM-DD).")


def _vendor_for(db: Session, rfq: PurchaseOrder, org_context: OrgContext, chosen_id: Optional[int]):
    """(template, supplier, locked): the template's vendor if it has one, else the chosen one."""
    template = load_template(db, rfq)
    template_vendor = load_supplier(db, template.supplier_id, org_context.org_id) if template and template.supplier_id else None
    if template_vendor is not None:
        if chosen_id and int(chosen_id) != template_vendor.supplier_id:
            raise HTTPException(
                status_code=422,
                detail=f"This RFQ came from template '{template.name}', which fixes the vendor as {template_vendor.name}.",
            )
        return template, template_vendor, True
    supplier = load_supplier(db, chosen_id, org_context.org_id) if chosen_id else None
    if chosen_id and supplier is None:
        raise HTTPException(status_code=404, detail="Vendor not available to this organisation")
    return template, supplier, False


# ── What the conversion screen needs ──────────────────────────────────────────
@RfqConversionRouter.get("/{rfq_id}/convert-to-po")
def conversion_context(
    rfq_id: int,
    supplier_id: Optional[int] = None,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    user: User = Depends(get_current_user),
):
    _authorise(user)
    rfq = _load_rfq(db, rfq_id, org_context)
    _assert_not_converted(db, rfq)
    template, supplier, locked = _vendor_for(db, rfq, org_context, supplier_id)

    lines = []
    for line in active_lines(rfq):
        terms = vendor_terms(db, line, supplier)
        lines.append({
            "po_item_id": line.id,
            "product_id": line.product_id,
            "item_code": line.item_code,
            "description": line.description,
            "unit": line.unit or "PCS",
            "quantity_requested": float(line.quantity_requested or line.quantity_ordered or 0),
            "min_order_qty": terms["min_order_qty"],
            "lead_time_days": terms["lead_time_days"],
        })
    return {
        "rfq": {"id": rfq.id, "po_number": rfq.po_number, "currency": rfq.currency or "USD",
                "goods_description": rfq.goods_description},
        "template": {"id": template.id, "name": template.name} if template else None,
        "vendor_locked": locked,
        "needs_vendor": supplier is None,
        "supplier": (
            {"id": supplier.supplier_id, "name": supplier.name, "code": supplier.code,
             "default_currency": supplier.default_currency}
            if supplier else None
        ),
        "lines": lines,
        "reasons": list(ADJUST_REASONS),
    }


# ── Convert ───────────────────────────────────────────────────────────────────
@RfqConversionRouter.post("/{rfq_id}/convert-to-po")
def convert_to_po(
    rfq_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    user: User = Depends(get_current_user),
):
    _authorise(user)
    rfq = _load_rfq(db, rfq_id, org_context, lock=True)
    from .OrderRouter import assert_no_open_revision
    assert_no_open_revision(rfq, "converting this RFQ to a purchase order")
    _assert_not_converted(db, rfq)

    template, supplier, _locked = _vendor_for(db, rfq, org_context, payload.get("supplier_id"))
    if supplier is None:
        raise HTTPException(status_code=422, detail="Choose the vendor for this purchase order.")
    if not supplier.is_active:
        raise HTTPException(status_code=409, detail="This vendor is inactive.")

    lines = {it.id: it for it in active_lines(rfq)}
    if not lines:
        raise HTTPException(status_code=422, detail="This RFQ has no lines to order.")
    given = {int(r["po_item_id"]): r for r in (payload.get("items") or []) if r.get("po_item_id") is not None}
    missing = [it.description for iid, it in lines.items() if iid not in given]
    if missing:
        raise HTTPException(status_code=422, detail="Give a price and quantity for every line. Missing: " + "; ".join(missing))
    unknown = [iid for iid in given if iid not in lines]
    if unknown:
        raise HTTPException(status_code=422, detail="Some lines do not belong to this RFQ.")

    built: List[Dict[str, Any]] = []
    for iid, line in lines.items():
        raw = given[iid]
        requested = Decimal(str(line.quantity_requested or line.quantity_ordered or 0))
        ordered = _dec(raw.get("quantity_ordered", requested), "quantity_ordered")
        # A price is optional: the vendor's proforma brings it. One that is given
        # is stored to the cent, so the total is built from that figure.
        price = _dec(raw.get("unit_price") or 0, "unit_price").quantize(Decimal("0.01"))
        if ordered <= 0:
            raise HTTPException(status_code=422, detail=f"'{line.description}': quantity must be greater than zero.")
        if price < 0:
            raise HTTPException(status_code=422, detail=f"'{line.description}': the unit price cannot be negative.")
        reason = (raw.get("qty_adjust_reason") or "").strip().upper() or None
        note = (raw.get("qty_adjust_note") or "").strip() or None
        if ordered != requested:
            if reason not in ADJUST_REASONS:
                raise HTTPException(
                    status_code=422,
                    detail=f"'{line.description}': the quantity differs from the request. Give a reason ({', '.join(ADJUST_REASONS)}).",
                )
            if ordered < requested and reason != "OTHER":
                raise HTTPException(status_code=422, detail=f"'{line.description}': a lower quantity can only be explained as OTHER.")
            if reason == "OTHER" and (not note or len(note) < MIN_NOTE):
                raise HTTPException(status_code=422, detail=f"'{line.description}': describe the reason in a short note.")
        else:
            reason, note = None, None
        built.append({"line": line, "requested": requested, "ordered": ordered, "price": price,
                      "reason": reason, "note": note})

    # ── Number and header ──
    org_id = rfq.org_id
    po_number = next_document_number(db, org_id, "PO")
    if not po_number:
        base = rfq.po_number
        po_number = base.replace("RFQ-", "PO-", 1) if base.startswith("RFQ-") else f"{base}-PO"
    if db.query(PurchaseOrder).filter(PurchaseOrder.po_number == po_number).first():
        po_number = f"{po_number}-{datetime.utcnow().strftime('%M%S')}"

    today = date.today()
    currency = (payload.get("currency") or rfq.currency or supplier.default_currency or "USD").upper()
    lead_days = max([vendor_terms(db, b["line"], supplier)["lead_time_days"] or 0 for b in built] or [0])
    eta = _eta(payload.get("eta_date")) or rfq.eta_date or ((today + timedelta(days=int(lead_days))) if lead_days else None)

    po = PurchaseOrder(
        po_number=po_number,
        doc_type="PO",
        order_source="DIRECT",
        source_template_id=rfq.source_template_id,
        parent_rfq_id=rfq.id,
        origin_rfq_number=rfq.po_number,
        request_id=rfq.request_id,
        supplier_id=supplier.supplier_id,
        company=supplier.name,
        supplier_name_at_issue=supplier.name,
        supplier_address_at_issue=supplier.address,
        goods_description=rfq.goods_description,
        material_ids=rfq.material_ids,
        status="ORDERED",
        status_label="PO Issued",
        lifecycle_stage="PO_ISSUED",
        stage_version=1,
        lifecycle_version=1,
        lifecycle_locked=False,
        payment_status="NONE",
        production_status="NOT_STARTED",
        shipment_status="NOT_SHIPPED",
        receipt_status="PENDING",
        currency=currency,
        sheet_type=rfq.sheet_type,
        consignee=rfq.consignee,
        year=rfq.year or today.year,
        urgent_action=rfq.urgent_action,
        order_mail_date=rfq.order_mail_date or today,
        quote_sent_date=rfq.quote_sent_date or today,
        quote_received_date=rfq.quote_received_date or today,
        pi_confirmed_date=None,
        eta_date=eta,
        freight_type=rfq.freight_type or "Sea Freight",
        remark=(payload.get("remark") or f"Converted directly from {rfq.po_number}"),
        org_id=org_id,
        created_by=user.id,
    )
    db.add(po)
    db.flush()

    total = Decimal("0")
    children: List[POItem] = []
    for b in built:
        orig = b["line"]
        line_total = (b["ordered"] * b["price"]).quantize(Decimal("0.01"))
        total += line_total
        child = POItem(
            org_id=org_id, po_id=po.id,
            source_rfq_item_id=orig.id, awarded_vendor_id=supplier.supplier_id,
            request_item_id=orig.request_item_id, product_id=orig.product_id,
            item_code=orig.item_code, description=orig.description,
            quantity_requested=b["requested"], quantity_ordered=b["ordered"], unit=orig.unit,
            draft_unit_price=orig.draft_unit_price or orig.unit_price,
            approved_unit_price=b["price"], unit_price=b["price"], po_unit_price=b["price"],
            total_price=line_total, currency=currency, item_status="ACTIVE", notes=orig.notes,
            qty_adjust_reason=b["reason"], qty_adjust_note=b["note"],
            created_by=user.id,
        )
        db.add(child)
        children.append(child)

        orig.awarded_vendor_id = supplier.supplier_id
        if b["price"] > 0:
            orig.approved_unit_price = b["price"]
            orig.unit_price = b["price"]
            orig.total_price = line_total
    po.total_amount = total
    po.balance_amount = total
    po.advance_amount = 0
    db.flush()

    for child, b in zip(children, built):
        if b["reason"]:
            LifecycleService.record_item_history(
                po=po, item=child, action="QUANTITY_ADJUSTED", field_name="quantity_ordered",
                old_value=b["requested"], new_value=b["ordered"],
                reason=f"{b['reason']}: {b['note']}" if b["note"] else f"Quantity changed for {b['reason']}",
                user_id=user.id, db=db,
            )
        learn_vendor_terms(db, po, child, b["reason"], currency, user.id)

    # ── The RFQ is awarded, as a split award leaves it ──
    rfq.lifecycle_stage = "QUOTE_APPROVED"
    rfq.status = "SOURCING"
    rfq.status_label = "Awarded"
    rfq.lifecycle_version += 1
    rfq.total_amount = total
    rfq.order_mail_date = rfq.order_mail_date or today
    rfq.quote_sent_date = rfq.quote_sent_date or today
    rfq.quote_received_date = rfq.quote_received_date or today

    db.add(POStageTransition(
        org_id=org_id, po_id=rfq.id, from_stage="CONFIRMED", to_stage="QUOTE_APPROVED",
        from_version=rfq.lifecycle_version - 1, to_version=rfq.lifecycle_version, transition_type="ADVANCE",
        comment=f"Converted directly to {po.po_number} for {supplier.name}, without a quote round",
        gate_checks_passed=True, created_by=user.id,
    ))
    db.add(POStageTransition(
        org_id=org_id, po_id=po.id, from_stage="DRAFT", to_stage="PO_ISSUED",
        from_version=1, to_version=1, transition_type="ADVANCE",
        comment=f"Issued directly from {rfq.po_number}", gate_checks_passed=True, created_by=user.id,
    ))
    db.refresh(po)
    parent_snap = LifecycleService.capture_po_snapshot(
        po=rfq, db=db, transition_type="STAGE_CHANGE",
        change_summary=f"Converted to Purchase Order {po.po_number} for {supplier.name}, without a quote round",
        diff_data={"converted_po": po.po_number, "template_id": rfq.source_template_id}, user_id=user.id,
    )
    db.flush()
    child_snap = LifecycleService.capture_po_snapshot(
        po=po, db=db, transition_type="INITIAL",
        change_summary=f"Created from {rfq.po_number} as official PO issued to {supplier.name}", user_id=user.id,
    )
    if child_snap is not None and parent_snap is not None:
        child_snap.parent_snapshot_id = parent_snap.id

    db.commit()
    db.refresh(po)
    db.refresh(rfq)
    try:
        from Services.search_service import sync_order_document
        sync_order_document(rfq)
        sync_order_document(po)
    except Exception:  # the index is a convenience; the orders are already saved
        logger.exception("Could not index converted order %s", po.po_number)

    return {
        "success": True,
        "rfq_id": rfq.id,
        "rfq_number": rfq.po_number,
        "po": {
            "id": po.id, "po_number": po.po_number, "supplier_id": supplier.supplier_id, "company": supplier.name,
            "total_amount": float(total), "currency": currency, "lifecycle_stage": po.lifecycle_stage,
            "lines": [
                {"id": it.id, "description": it.description,
                 "quantity_requested": float(it.quantity_requested), "quantity_ordered": float(it.quantity_ordered),
                 "unit_price": float(it.unit_price), "qty_adjust_reason": it.qty_adjust_reason}
                for it in po.items if not it.is_deleted
            ],
        },
    }

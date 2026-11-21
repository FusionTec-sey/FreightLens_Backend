"""Proforma invoices: numbering, variance against the PO, and payment state.

The PO is the commitment and the vendor's proforma is what gets paid. Every
payment carries a proforma_id (and the proforma's po_id), and this module is
the one place that turns those payments back into figures:

* each live proforma's status (APPROVED / PART_PAID / PAID), and
* the PO's advance_amount, balance_amount, payment_status and payment dates.

The PO columns stay as a mirror, written only from here and from the legacy
payment update/delete endpoints that call sync_payment_state, so reports,
registers and snapshots that read purchase_orders keep working unchanged.
"""
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from Model.containermgmt.Cinfo.Supplier import Supplier
from Model.containermgmt.Orders.OrderPayment import OrderPayment
from Model.containermgmt.Orders.POItem import POItem
from Model.containermgmt.Orders.ProformaInvoice import ProformaInvoice
from Model.containermgmt.Orders.PurchaseOrder import PurchaseOrder
from Services.document_number_service import next_document_number

# Statuses a payment may be recorded against, and that count towards what the PO owes.
PAYABLE_STATUSES = ("APPROVED", "PART_PAID", "PAID")
OPEN_STATUSES = ("RECEIVED",) + PAYABLE_STATUSES
TOLERANCE = 0.01


def _f(value) -> float:
    return float(value) if value is not None else 0.0


def next_proforma_number(db: Session, po: PurchaseOrder) -> str:
    """Our reference. A configured PI series wins; otherwise PI-<PO number>-<n>.

    The fallback is derived from the PO so it needs no counter row, and it
    counts every proforma the PO has ever had (deleted ones too) so a number is
    never reused.
    """
    configured = next_document_number(db, po.org_id, "PI")
    if configured:
        return configured
    existing = db.query(ProformaInvoice).filter(ProformaInvoice.po_id == po.id).count()
    n = existing + 1
    candidate = f"PI-{po.po_number}-{n}"
    while db.query(ProformaInvoice).filter(ProformaInvoice.proforma_number == candidate).first():
        n += 1
        candidate = f"PI-{po.po_number}-{n}"
    return candidate


def po_line_price(item: POItem) -> Optional[Decimal]:
    for candidate in (item.po_unit_price, item.approved_unit_price, item.unit_price):
        if candidate is not None and Decimal(str(candidate)) > 0:
            return Decimal(str(candidate))
    return None


def variance_threshold(po: PurchaseOrder, db: Session) -> Decimal:
    from Routes.Orders.LifecycleService import DEFAULT_VARIANCE_THRESHOLD
    threshold = Decimal(str(DEFAULT_VARIANCE_THRESHOLD))
    if po.supplier_id:
        supplier = db.query(Supplier).filter(Supplier.supplier_id == po.supplier_id).first()
        if supplier is not None and supplier.variance_threshold_pct is not None:
            threshold = Decimal(str(supplier.variance_threshold_pct))
    return threshold


def evaluate_variance(po: PurchaseOrder, lines: List[Dict[str, Any]], db: Session) -> Dict[str, Any]:
    """Compare proforma lines with the PO lines they answer.

    `lines` are dicts with po_item_id, quantity, unit_price. A price over the
    supplier's threshold, or any quantity that differs from the PO line, is a
    variance that needs Approve_Variance before the proforma can be approved.
    Lines with no PO line (extra charges) are reported but not scored.
    Mutates each line dict with po_unit_price and variance_pct.
    """
    threshold = variance_threshold(po, db)
    by_id = {it.id: it for it in (po.items or []) if not it.is_deleted}
    findings: List[Dict[str, Any]] = []
    compared = 0

    for line in lines:
        item = by_id.get(line.get("po_item_id"))
        line["po_unit_price"] = None
        line["variance_pct"] = None
        if item is None:
            continue
        base = po_line_price(item)
        price = Decimal(str(line.get("unit_price") or 0))
        if base is not None:
            compared += 1
            line["po_unit_price"] = base
            pct = (abs(price - base) / base) * Decimal("100")
            line["variance_pct"] = round(pct, 2)
            if pct > threshold:
                findings.append({
                    "po_item_id": item.id, "kind": "price", "description": item.description,
                    "po_price": float(base), "proforma_price": float(price),
                    "variance_pct": float(round(pct, 2)), "threshold_pct": float(threshold),
                })
        qty = Decimal(str(line.get("quantity") or 0))
        ordered = Decimal(str(item.quantity_ordered or 0))
        if ordered > 0 and qty != ordered:
            findings.append({
                "po_item_id": item.id, "kind": "quantity", "description": item.description,
                "po_quantity": float(ordered), "proforma_quantity": float(qty),
            })

    if not compared and not findings:
        status = "NONE"
    elif findings:
        status = "EXCEEDED"
    else:
        status = "WITHIN"
    return {
        "status": status,
        "threshold_pct": float(threshold),
        "findings": findings,
        "message": (
            f"{len(findings)} difference(s) from the PO need approval" if findings
            else "Within tolerance" if compared else "No PO prices to compare"
        ),
    }


def price_unpriced_po_lines(db: Session, po: PurchaseOrder, pf: ProformaInvoice, user_id: Optional[int]) -> int:
    """Put the approved proforma's prices on PO lines that were issued without one.

    A PO converted straight from an RFQ has no prices; they arrive on the
    vendor's proforma. Once that is approved the PO should say what was agreed,
    so its lines and total are filled in. A line that already has a price is
    never touched: a difference there is a variance, approved on its own terms.
    Returns how many lines were priced.
    """
    from Routes.Orders.LifecycleService import LifecycleService

    by_id = {it.id: it for it in (po.items or []) if not it.is_deleted}
    priced = 0
    for line in pf.items:
        item = by_id.get(line.po_item_id)
        if item is None or po_line_price(item) is not None:
            continue
        price = Decimal(str(line.unit_price or 0))
        if price <= 0:
            continue
        item.unit_price = price
        item.po_unit_price = price
        item.approved_unit_price = price
        item.total_price = (Decimal(str(item.quantity_ordered or 0)) * price).quantize(Decimal("0.01"))
        LifecycleService.record_item_history(
            po=po, item=item, action="PRICE_FROM_PROFORMA", field_name="unit_price",
            old_value=None, new_value=price,
            reason=f"Price set from approved proforma {pf.proforma_number}",
            user_id=user_id, db=db,
        )
        priced += 1
    if priced:
        po.total_amount = sum((it.total_price or 0) for it in by_id.values())
    return priced


def payable_total(po: PurchaseOrder) -> float:
    """What the PO owes: its live proformas, else the PO's own total."""
    live = [pf for pf in (po.proformas or []) if not pf.is_deleted and pf.status in PAYABLE_STATUSES]
    if live:
        return sum(_f(pf.total_amount) for pf in live)
    total = _f(po.total_amount)
    if total <= 0:
        total = sum(_f(it.total_price) for it in (po.items or []) if not it.is_deleted)
    return total


def paid_on(db: Session, proforma_id: int) -> float:
    rows = db.query(OrderPayment).filter(
        OrderPayment.proforma_id == proforma_id, OrderPayment.is_deleted == False  # noqa: E712
    ).all()
    return sum(_f(p.amount) for p in rows)


def sync_payment_state(db: Session, po: PurchaseOrder) -> None:
    """Recompute proforma statuses and the PO's payment mirror from the payments."""
    payments = db.query(OrderPayment).filter(
        OrderPayment.po_id == po.id, OrderPayment.is_deleted == False  # noqa: E712
    ).all()

    for pf in (po.proformas or []):
        if pf.is_deleted or pf.status not in PAYABLE_STATUSES:
            continue
        paid = sum(_f(p.amount) for p in payments if p.proforma_id == pf.id)
        total = _f(pf.total_amount)
        if total > 0 and paid >= total - TOLERANCE:
            pf.status = "PAID"
        elif paid > TOLERANCE:
            pf.status = "PART_PAID"
        else:
            pf.status = "APPROVED"

    total_paid = sum(_f(p.amount) for p in payments)
    total = payable_total(po)
    if total > 0 and not any(not pf.is_deleted and pf.status in PAYABLE_STATUSES for pf in (po.proformas or [])):
        # No proforma yet: keep the PO total the old endpoints would have used.
        po.total_amount = po.total_amount if _f(po.total_amount) > 0 else total

    po.advance_amount = total_paid
    po.balance_amount = max(0.0, total - total_paid)

    advances = [p.paid_date for p in payments if p.payment_type == "ADVANCE" and p.paid_date]
    if advances:
        po.payment_date = min(advances)
    elif not any(p.paid_date for p in payments):
        po.payment_date = None
    closing = [p.paid_date for p in payments if p.payment_type in ("BALANCE", "FINAL") and p.paid_date]
    dated = [p.paid_date for p in payments if p.paid_date]
    if closing:
        po.balance_payment_date = max(closing)
    elif total > 0 and total_paid >= total - TOLERANCE and dated:
        po.balance_payment_date = max(dated)
    else:
        po.balance_payment_date = None

    if total > 0 and total_paid >= total - TOLERANCE:
        po.payment_status = "FULLY_PAID"
    elif total_paid > 0:
        po.payment_status = "PART_PAID"
    else:
        po.payment_status = "NONE"


def revision_entry(user_id: Optional[int], reason: str, summary: str) -> Dict[str, Any]:
    return {
        "at": date.today().isoformat(),
        "by": user_id,
        "reason": reason.strip(),
        "summary": summary,
    }

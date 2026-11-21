"""Converting a confirmed RFQ straight into a purchase order, with no quote round.

Some buying does not need bidding: the vendor is already known, or the items
are standing ones. From Vendor Quotes & Bidding a confirmed RFQ can either be
sent to vendors for quotes or converted to a PO. Converting asks only which
vendor and, if it has to change, the quantity (a vendor minimum, a pack multiple).
The price is not asked: it arrives on the vendor's proforma and is put on the PO
when that is approved.

The vendor comes from the RFQ's template when it was made from one. An RFQ
deliberately carries no vendor while it is a sourcing document, so what it
keeps is the template reference (purchase_orders.source_template_id); the
vendor is read from the template only at conversion. An RFQ with no template
has no vendor to read, and the buyer chooses one.
"""
from decimal import Decimal, ROUND_CEILING
from typing import Any, Dict, List, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from Model.containermgmt.Cinfo.Supplier import Supplier
from Model.containermgmt.Orders.OrderTemplate import OrderTemplate
from Model.containermgmt.Orders.POItem import POItem
from Model.containermgmt.Orders.Product import ProductSupplier
from Model.containermgmt.Orders.PurchaseOrder import PurchaseOrder

ADJUST_REASONS = ("MOQ", "PACK_MULTIPLE", "OTHER")
MIN_NOTE = 5


def suggest_quantity(needed: Decimal, moq: Optional[Decimal], multiple: Optional[Decimal] = None) -> Dict[str, Any]:
    """Raise to the vendor's minimum, then round up to their pack multiple.

    A suggestion only: the buyer confirms it and says why it differs.
    """
    quantity = needed
    reason = None
    if moq is not None and moq > 0 and quantity < moq:
        quantity = moq
        reason = "MOQ"
    if multiple is not None and multiple > 0:
        rounded = (quantity / multiple).to_integral_value(rounding=ROUND_CEILING) * multiple
        if rounded != quantity:
            quantity = rounded
            reason = reason or "PACK_MULTIPLE"
    return {"quantity": quantity, "reason": reason if quantity != needed else None}


def load_supplier(db: Session, supplier_id: Optional[int], org_id: int) -> Optional[Supplier]:
    if not supplier_id:
        return None
    return db.query(Supplier).filter(
        Supplier.supplier_id == supplier_id,
        Supplier.is_deleted != True,  # noqa: E712
        or_(Supplier.is_shared == True, Supplier.org_id == org_id),  # noqa: E712
    ).first()


def active_lines(rfq: PurchaseOrder) -> List[POItem]:
    return [it for it in (rfq.items or []) if not it.is_deleted and it.item_status != "USER_REMOVED"]


def load_template(db: Session, rfq: PurchaseOrder) -> Optional[OrderTemplate]:
    if not rfq.source_template_id:
        return None
    return db.query(OrderTemplate).filter(
        OrderTemplate.id == rfq.source_template_id, OrderTemplate.is_deleted != True  # noqa: E712
    ).first()


def vendor_terms(db: Session, line: POItem, supplier: Optional[Supplier]) -> Dict[str, Any]:
    if supplier is None or not line.product_id:
        return {"min_order_qty": None, "lead_time_days": None}
    link = db.query(ProductSupplier).filter(
        ProductSupplier.product_id == line.product_id,
        ProductSupplier.supplier_id == supplier.supplier_id,
        ProductSupplier.is_deleted != True,  # noqa: E712
    ).first()
    if link is None:
        return {"min_order_qty": None, "lead_time_days": None}
    return {
        "min_order_qty": float(link.min_order_qty) if link.min_order_qty is not None else None,
        "lead_time_days": link.lead_time_days,
    }


def learn_vendor_terms(db: Session, po: PurchaseOrder, item: POItem, reason: Optional[str],
                       currency: str, user_id: Optional[int]) -> None:
    """Keep the product-vendor link current: the price just agreed, and a minimum that was hit.

    The cost follows the order because that is what was agreed. A minimum is
    only ever raised, never lowered, so a figure a buyer typed is not undone by
    one small order.
    """
    if not item.product_id:
        return
    link = db.query(ProductSupplier).filter(
        ProductSupplier.product_id == item.product_id,
        ProductSupplier.supplier_id == po.supplier_id,
        ProductSupplier.is_deleted != True,  # noqa: E712
    ).first()
    learned_moq = item.quantity_ordered if reason == "MOQ" else None
    if link is None:
        db.add(ProductSupplier(
            org_id=po.org_id, product_id=item.product_id, supplier_id=po.supplier_id,
            unit_cost=item.unit_price if item.unit_price and Decimal(str(item.unit_price)) > 0 else None,
            currency=currency, min_order_qty=learned_moq,
            is_default=False, notes=f"Learned from {po.po_number}", created_by=user_id,
        ))
        return
    if item.unit_price and Decimal(str(item.unit_price)) > 0:
        link.unit_cost = item.unit_price
        link.currency = currency or link.currency
    if learned_moq is not None and (link.min_order_qty is None or Decimal(str(link.min_order_qty)) < learned_moq):
        link.min_order_qty = learned_moq
    link.updated_by = user_id

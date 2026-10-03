"""Atomic receipt posting. Lock order: purchase order, receipt, ordered PO lines.

No stock ledger is implied: this service only maintains purchasing received totals.
No network calls occur while locks are held.
"""
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException

from Model.containermgmt.Orders.PurchaseOrder import PurchaseOrder
from Model.containermgmt.Orders.POItem import POItem
from Model.containermgmt.Orders.OrderPackingList import OrderPackingList, PackingListItem
from Model.containermgmt.Orders.OrderShipment import OrderShipment
from Model.containermgmt.Container.ContainerDetails import ContainerDetails
from Model.containermgmt.Orders.OrderStatus import OrderStatus
from Model.containermgmt.Orders.Notification import Notification
from Utils.org_filter import apply_org_filter


def lock_order(db, po_id, context):
    query = db.query(PurchaseOrder).filter(PurchaseOrder.id == po_id, PurchaseOrder.is_deleted == False)
    po = apply_org_filter(query, PurchaseOrder, context).with_for_update(of=PurchaseOrder).populate_existing().first()
    if po is None:
        raise HTTPException(404, "Purchase order not found")
    return po


def validate_links(db, po, receipt, lines):
    """Check explicit same-parent ownership even for users allowed multiple tenants."""
    if receipt.packing_list_id:
        packing = db.query(OrderPackingList).filter(
            OrderPackingList.id == receipt.packing_list_id, OrderPackingList.po_id == po.id,
            OrderPackingList.org_id == po.org_id, OrderPackingList.is_deleted == False,
        ).first()
        if packing is None:
            raise HTTPException(400, "Packing list does not belong to this purchase order")
    if receipt.container_id:
        container = db.query(ContainerDetails).filter(
            ContainerDetails.Container_ID == receipt.container_id, ContainerDetails.org_id == po.org_id,
            ContainerDetails.is_deleted == False,
        ).first()
        shipment = db.query(OrderShipment).filter(
            OrderShipment.po_id == po.id, OrderShipment.org_id == po.org_id,
            OrderShipment.container_id == receipt.container_id, OrderShipment.is_deleted == False,
        ).first()
        if container is None or shipment is None:
            raise HTTPException(400, "Container does not belong to this purchase order")
    items = db.query(POItem).filter(
        POItem.po_id == po.id, POItem.org_id == po.org_id, POItem.is_deleted == False,
    ).order_by(POItem.id).with_for_update(of=POItem).populate_existing().all()
    item_map = {item.id: item for item in items}
    seen = set()
    for line in lines:
        item = item_map.get(line.po_item_id)
        if item is None or item.item_status != "ACTIVE":
            raise HTTPException(400, "Receipt line must reference an active item on this purchase order")
        if line.po_item_id in seen:
            raise HTTPException(400, "Duplicate purchase order item")
        seen.add(line.po_item_id)
        if line.unit != item.unit:
            raise HTTPException(400, "Receipt unit must match the purchase order item")
        if line.packing_item_id:
            packed = db.query(PackingListItem).filter(
                PackingListItem.id == line.packing_item_id,
                PackingListItem.packing_list_id == receipt.packing_list_id,
                PackingListItem.po_item_id == line.po_item_id, PackingListItem.is_deleted == False,
            ).first()
            if not receipt.packing_list_id or packed is None:
                raise HTTPException(400, "Packing item does not belong to this receipt's packing list and PO item")
    return item_map


def post_receipt(db, po, receipt, lines, items, user_id):
    if not lines or not any(line.received_quantity > 0 for line in lines):
        raise HTTPException(400, "A submitted receipt must contain received goods")
    for line in lines:
        item = items[line.po_item_id]
        updated = Decimal(item.quantity_received or 0) + line.received_quantity
        if updated > Decimal("9999999999.99"):
            raise HTTPException(400, "Received quantity exceeds the supported limit")
        item.quantity_received = updated
        item.updated_by = user_id
    receipt.status = "SUBMITTED"
    receipt.submitted_at = datetime.now(timezone.utc)
    receipt.updated_by = user_id
    active = [item for item in items.values() if item.item_status == "ACTIVE"]
    complete = bool(active) and all(item.quantity_received >= item.quantity_ordered for item in active)
    po.receipt_status = "RECEIVED" if complete else "PARTIAL"
    po.updated_by = user_id
    if complete:
        received = db.query(OrderStatus).filter(OrderStatus.code == "RECEIVED", OrderStatus.is_deleted == False).first()
        if received:
            po.status_id, po.status, po.status_label = received.id, "RECEIVED", "Received"
    db.add(Notification(
        org_id=po.org_id, event_type="GOODS_RECEIVED", title="Goods receipt submitted",
        message=f"Receipt #{receipt.receipt_number} submitted for PO {po.po_number} ({po.receipt_status}).",
        link_entity_type="RECEIPT", link_entity_id=receipt.id,
    ))

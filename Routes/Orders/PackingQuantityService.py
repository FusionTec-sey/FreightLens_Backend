"""How much of a purchase order is still to be packed.

A purchase order can ride on as many containers as it takes, so every quantity
question here is asked per *item*, never per order:

    remaining(item) = quantity_ordered - quantity_packed - draft_held(item)

``quantity_packed`` is the running total committed by CONFIRMED packing lists
and lives on the row. ``draft_held`` is the same item's quantity sitting on
other open DRAFT lists; it is summed live rather than written anywhere, so an
abandoned draft needs no release path -- deleting or confirming it changes the
sum by itself.

An item with nothing remaining is not offered at all. It is not seeded as a
zero row either: the second container's packing list shows only what the first
one left.
"""

from decimal import Decimal
from typing import Dict, Iterable, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from Model.containermgmt.Orders.POItem import POItem
from Model.containermgmt.Orders.OrderPackingList import OrderPackingList, PackingListItem

DRAFT = "DRAFT"


def _f(value) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def draft_held_map(
    db: Session,
    po_ids: Optional[Iterable[int]] = None,
    exclude_packing_list_id: Optional[int] = None,
) -> Dict[int, float]:
    """Quantity per po_item_id currently claimed by open draft packing lists.

    The list being edited is excluded, so a draft never holds against itself.
    """
    query = (
        db.query(
            PackingListItem.po_item_id,
            func.coalesce(func.sum(PackingListItem.quantity_packed), 0),
        )
        .join(OrderPackingList, PackingListItem.packing_list_id == OrderPackingList.id)
        .filter(
            PackingListItem.po_item_id.isnot(None),
            PackingListItem.is_deleted == False,
            OrderPackingList.is_deleted == False,
            OrderPackingList.status == DRAFT,
        )
    )

    po_ids = list(po_ids or [])
    if po_ids:
        query = query.filter(PackingListItem.po_id.in_(po_ids))
    if exclude_packing_list_id:
        query = query.filter(OrderPackingList.id != exclude_packing_list_id)

    return {row[0]: _f(row[1]) for row in query.group_by(PackingListItem.po_item_id).all()}


def remaining_for_item(item: POItem, held: float = 0.0) -> float:
    """What may still be packed for this line, never below zero."""
    return max(
        0.0,
        _f(item.quantity_ordered) - _f(item.quantity_packed) - _f(held),
    )


def is_packable_item(item: POItem) -> bool:
    return (
        not item.is_deleted
        and (item.item_status or "ACTIVE").upper() == "ACTIVE"
    )


def open_items(
    po,
    held_map: Optional[Dict[int, float]] = None,
):
    """(item, remaining) for every line of ``po`` with something left to pack.

    Lines with nothing remaining are dropped, not returned as zeroes.
    """
    held_map = held_map or {}
    out = []
    for item in (po.items or []):
        if not is_packable_item(item):
            continue
        remaining = remaining_for_item(item, held_map.get(item.id, 0.0))
        if remaining > 0:
            out.append((item, remaining))
    return out


def po_open_quantity(po, held_map: Optional[Dict[int, float]] = None) -> float:
    """Total quantity still to be packed across the order's active lines."""
    return sum(remaining for _, remaining in open_items(po, held_map))

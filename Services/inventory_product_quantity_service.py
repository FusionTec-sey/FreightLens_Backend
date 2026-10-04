"""Exact product-level quantity projection from authoritative location balances."""
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import func

from Model.containermgmt.Inventory.StockLedger import StockBalance
from Utils.org_filter import apply_org_filter


ZERO = Decimal("0")


def stock_quantity_summary_subquery(db, context):
    """Return one scoped SQL row per product for filters and dashboard counts.

    `unit_count` is mandatory for every consumer: quantities may be compared with
    catalogue thresholds only when zero or one authoritative base unit exists.
    """
    query = db.query(
        StockBalance.product_id.label("product_id"),
        func.sum(StockBalance.on_hand).label("on_hand"),
        func.count(func.distinct(StockBalance.base_unit)).label("unit_count"),
    ).filter(StockBalance.is_deleted.is_(False))
    query = apply_org_filter(query, StockBalance, context)
    return query.group_by(StockBalance.product_id).subquery()


def _exact(value):
    return format(value or ZERO, ".6f")


def product_quantity_totals(db, context, product_ids):
    """Return bounded company-wide totals without reading Product.current_stock.

    Separate base units are never summed. A mixed-unit product is surfaced as an
    explicit reconciliation error so callers cannot present a false total.
    """
    if context.org_id not in context.allowed_org_ids:
        raise PermissionError("Inventory quantity company denied")
    ids = {value for value in product_ids if type(value) is int and value > 0}
    if len(ids) > 10000:
        raise ValueError("Inventory quantity projection is too large")
    if not ids:
        return {}
    query = db.query(
        StockBalance.product_id,
        StockBalance.base_unit,
        func.sum(StockBalance.on_hand).label("on_hand"),
        func.sum(StockBalance.reserved).label("reserved"),
        func.sum(StockBalance.damaged).label("damaged"),
        func.sum(StockBalance.quarantined).label("quarantined"),
    ).filter(
        StockBalance.org_id == context.org_id,
        StockBalance.product_id.in_(ids),
        StockBalance.is_deleted.is_(False),
    ).group_by(StockBalance.product_id, StockBalance.base_unit)
    rows = apply_org_filter(query, StockBalance, context).all()
    grouped = defaultdict(list)
    for row in rows:
        grouped[row.product_id].append(row)
    result = {}
    for product_id in ids:
        product_rows = grouped.get(product_id, [])
        if not product_rows:
            result[product_id] = {
                "status": "NO_BALANCE", "base_unit": None,
                "on_hand": "0.000000", "reserved": "0.000000",
                "available": "0.000000", "damaged": "0.000000",
                "quarantined": "0.000000",
            }
            continue
        if len(product_rows) != 1:
            result[product_id] = {
                "status": "MIXED_UNITS", "base_unit": None,
                "on_hand": None, "reserved": None, "available": None,
                "damaged": None, "quarantined": None,
            }
            continue
        row = product_rows[0]
        available = row.on_hand - row.reserved - row.damaged - row.quarantined
        result[product_id] = {
            "status": "AVAILABLE", "base_unit": row.base_unit,
            "on_hand": _exact(row.on_hand), "reserved": _exact(row.reserved),
            "available": _exact(available), "damaged": _exact(row.damaged),
            "quarantined": _exact(row.quarantined),
        }
    return result

"""Read-only central valuation/physical readiness; never finalises accounting."""
from decimal import Decimal
from sqlalchemy import func
from Model.containermgmt.Inventory.CostPool import BranchCostPool
from Model.containermgmt.Inventory.StockLedger import StockBalance
from Model.containermgmt.Inventory.Valuation import InventoryValuation
from Model.containermgmt.Orders.Product import Product
from Utils.org_filter import apply_org_filter


ZERO = Decimal('0.000000')


def _owned(db, model, context):
    return apply_org_filter(db.query(model).filter(
        model.org_id == context.org_id, model.is_deleted.is_(False)), model, context)


def reconciliation_readiness(db, context, cost_pool_id, *, page, limit):
    """Compare current physical quantity with each product's immutable pool head.

    This is deliberately diagnostic. A READY row says only that the current central
    quantity agrees with the current physical projection in one base unit. It does
    not certify evidence retention, accounting export, offline delivery or a period.
    """
    if type(cost_pool_id) is not int or cost_pool_id <= 0:
        raise ValueError('Positive cost-pool identity required')
    if type(page) is not int or type(limit) is not int or page < 1 or not 1 <= limit <= 100:
        raise ValueError('Bounded reconciliation page required')
    physical_ids = _owned(db, StockBalance, context).join(BranchCostPool,
        (BranchCostPool.branch_id == StockBalance.branch_id) &
        (BranchCostPool.org_id == StockBalance.org_id)).filter(
            BranchCostPool.cost_pool_id == cost_pool_id,
            BranchCostPool.is_deleted.is_(False)).with_entities(
                StockBalance.product_id.label('product_id'))
    valuation_ids = _owned(db, InventoryValuation, context).filter_by(
        cost_pool_id=cost_pool_id).with_entities(
            InventoryValuation.product_id.label('product_id'))
    sources = physical_ids.union(valuation_ids).subquery()
    products = _owned(db, Product, context).join(
        sources, sources.c.product_id == Product.id).filter(
            Product.is_shared.is_(False)).with_entities(
                Product.id, Product.name).order_by(Product.name, Product.id)
    total = products.count()
    page_rows = products.offset((page - 1) * limit).limit(limit).all()
    product_ids = [row.id for row in page_rows]
    if not product_ids:
        return dict(items=[], total=total, page=page, limit=limit,
            pages=max(1, (total + limit - 1) // limit))
    physical_rows = _owned(db, StockBalance, context).join(BranchCostPool,
        (BranchCostPool.branch_id == StockBalance.branch_id) &
        (BranchCostPool.org_id == StockBalance.org_id)).filter(
            BranchCostPool.cost_pool_id == cost_pool_id,
            BranchCostPool.is_deleted.is_(False),
            StockBalance.product_id.in_(product_ids)).with_entities(
                StockBalance.product_id, StockBalance.base_unit,
                func.sum(StockBalance.on_hand).label('quantity')).group_by(
                    StockBalance.product_id, StockBalance.base_unit).all()
    physical = {}
    for product_id, base_unit, quantity in physical_rows:
        physical.setdefault(product_id, []).append((base_unit, Decimal(quantity)))
    value_rows = _owned(db, InventoryValuation, context).filter(
        InventoryValuation.cost_pool_id == cost_pool_id,
        InventoryValuation.product_id.in_(product_ids)).order_by(
            InventoryValuation.product_id,
            InventoryValuation.version.desc(), InventoryValuation.id.desc()).all()
    heads = {}
    for row in value_rows:
        heads.setdefault(row.product_id, row)
    items = []
    for product in page_rows:
        quantities = physical.get(product.id, [])
        units = sorted(unit for unit, _ in quantities)
        head = heads.get(product.id)
        physical_quantity = quantities[0][1] if len(quantities) == 1 else (
            ZERO if not quantities else None)
        if len(quantities) > 1 or (head is not None and units and
                head.base_unit != units[0]):
            readiness = 'UNIT_MISMATCH'; difference = None
        elif head is None:
            readiness = 'MISSING_VALUATION'; difference = None
        else:
            difference = physical_quantity - Decimal(head.pool_quantity)
            readiness = 'READY' if difference == ZERO else 'QUANTITY_MISMATCH'
        items.append(dict(product_id=product.id, product_name=product.name,
            physical_base_units=units,
            physical_quantity=None if physical_quantity is None else
                format(physical_quantity, '.6f'),
            valuation_id=head.id if head else None,
            valuation_version=head.version if head else None,
            valuation_base_unit=head.base_unit if head else None,
            pool_quantity=format(head.pool_quantity, '.6f') if head else None,
            pool_value_scr=format(head.pool_value_scr, '.6f') if head else None,
            difference=None if difference is None else format(difference, '.6f'),
            readiness=readiness))
    return dict(items=items, total=total, page=page, limit=limit,
        pages=max(1, (total + limit - 1) // limit))

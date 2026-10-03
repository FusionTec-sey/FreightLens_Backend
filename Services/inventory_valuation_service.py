"""Internal approved opening valuation adapter; no public financial posting.

The mandatory guard must authorize the actor, cost evidence and central writer on
every attempt. No client-supplied quantity, pool or cumulative cost is trusted.
UNRECONCILED entries are not final shared-pool accounts or offline sale costs.
"""
from decimal import Decimal
from Model.containermgmt.Inventory.Valuation import InventoryValuation
from Model.containermgmt.Inventory.StockLedger import StockBalance, StockMovement
from Model.containermgmt.Inventory.CostPool import BranchCostPool, InventoryCostPool
from Model.containermgmt.Inventory.Location import InventoryBranch, StockLocation
from Model.containermgmt.Orders.Product import Product
from Services.inventory_costing_service import CostPool, CostBalance, receive, COSTING_POLICY_VERSION
from Services.inventory_posting_service import execute_once, PostingEffect, PostingConflict
from Utils.org_filter import apply_org_filter


def record_opening_value(factory, context, actor_id, operation_key, *, balance_id,
                         expected_version, goods_value_scr, additional_cost_scr,
                         reason, authorize):
    if not callable(authorize):
        raise ValueError("Valuation requires a cost evidence and authority guard")
    if type(expected_version) is not int or expected_version < 0:
        raise ValueError("Expected valuation version must be nonnegative")
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 500:
        raise ValueError("A bounded valuation reason is required")
    # Reuse exact range/precision validation before fingerprinting any money.
    receive(CostBalance(CostPool(context.org_id, 1, 1), Decimal(0), Decimal(0)),
            Decimal(1), goods_value_scr, additional_cost_scr)
    request = dict(balance_id=balance_id, expected_version=expected_version,
        goods_value_scr=format(goods_value_scr, '.6f'), additional_cost_scr=format(additional_cost_scr, '.6f'), reason=reason.strip())
    loaded = {}

    def guard(db):
        authorize(db)
        source = apply_org_filter(db.query(StockBalance).filter(StockBalance.id == balance_id,
            StockBalance.org_id == context.org_id, StockBalance.is_deleted.is_(False)), StockBalance, context).one_or_none()
        if source is None:
            raise LookupError("Valuation stock source not found")
        # Product lock serializes absent pool/product streams and future changes.
        product = apply_org_filter(db.query(Product.id).filter(Product.id == source.product_id,
            Product.org_id == context.org_id, Product.is_deleted.is_(False), Product.is_shared.is_(False)),
            Product, context).with_for_update().one_or_none()
        if product is None:
            raise LookupError("Valuation product not found")
        pool = db.query(InventoryCostPool).join(BranchCostPool,
            (BranchCostPool.cost_pool_id == InventoryCostPool.id) & (BranchCostPool.org_id == InventoryCostPool.org_id))
        pool = pool.join(InventoryBranch, (InventoryBranch.id == BranchCostPool.branch_id) & (InventoryBranch.org_id == BranchCostPool.org_id))
        pool = pool.join(StockLocation, (StockLocation.branch_id == InventoryBranch.id) & (StockLocation.org_id == InventoryBranch.org_id))
        pool = apply_org_filter(pool.filter(BranchCostPool.branch_id == source.branch_id,
            StockLocation.id == source.location_id, InventoryCostPool.org_id == context.org_id,
            InventoryCostPool.is_active.is_(True), InventoryCostPool.is_deleted.is_(False),
            BranchCostPool.is_deleted.is_(False), InventoryBranch.is_active.is_(True),
            InventoryBranch.is_deleted.is_(False), StockLocation.is_active.is_(True), StockLocation.is_deleted.is_(False)),
            InventoryCostPool, context).with_for_update(read=True).one_or_none()
        if pool is None:
            raise ValueError("An active explicit branch cost-pool mapping is required")
        opening = db.query(StockMovement).filter_by(org_id=context.org_id, balance_id=balance_id,
            version=1, kind="OPENING", is_deleted=False).one_or_none()
        if opening is None or opening.on_hand_delta <= 0 or source.policy_config is None:
            raise ValueError("A positive policy-backed opening movement is required")
        query = apply_org_filter(db.query(InventoryValuation).filter_by(org_id=context.org_id,
            cost_pool_id=pool.id, product_id=source.product_id, is_deleted=False), InventoryValuation, context)
        latest = query.order_by(InventoryValuation.version.desc()).first()
        version = latest.version if latest else 0
        own = latest is not None and latest.operation_key == operation_key
        if version != expected_version + (1 if own else 0):
            raise PostingConflict("Valuation version changed; refresh before posting")
        if latest and latest.base_unit != source.base_unit:
            raise PostingConflict("Valuation base unit differs from the source")
        loaded.update(source=source, opening=opening, pool=pool, latest=latest)

    def apply(db):
        source, opening, pool, latest = (loaded[k] for k in ("source", "opening", "pool", "latest"))
        if db.query(InventoryValuation.id).filter_by(org_id=context.org_id, balance_id=balance_id, source_version=1).first():
            raise PostingConflict("Opening movement already has a valuation")
        before = CostBalance(CostPool(context.org_id, pool.id, source.product_id),
            latest.pool_quantity if latest else Decimal(0), latest.pool_value_scr if latest else Decimal(0))
        after = receive(before, opening.on_hand_delta, goods_value_scr, additional_cost_scr)
        row = InventoryValuation(org_id=context.org_id, operation_key=operation_key, cost_pool_id=pool.id,
            product_id=source.product_id, balance_id=balance_id, source_version=1, version=expected_version + 1,
            base_unit=source.base_unit, quantity=opening.on_hand_delta, goods_value_scr=goods_value_scr,
            additional_cost_scr=additional_cost_scr, pool_quantity=after.quantity, pool_value_scr=after.value_scr,
            calculation_policy=COSTING_POLICY_VERSION, currency="SCR", status="UNRECONCILED", reason=reason.strip(), created_by=actor_id)
        db.add(row); db.flush()
        result = {"valuation_id": row.id, "cost_pool_id": pool.id, "product_id": source.product_id,
            "version": row.version, "pool_quantity": format(after.quantity, '.6f'),
            "pool_value_scr": format(after.value_scr, '.6f'), "average_cost_scr": format(after.average_cost_scr, '.6f'),
            "status": row.status}
        return PostingEffect(result, {"kind": "inventory.valuation.opening-recorded", "valuation_id": row.id})

    return execute_once(factory, context, actor_id, operation_key, "inventory.valuation.opening.v1", request, apply, authorize=guard)

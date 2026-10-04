"""Reviewed product/pool checkpoint; never rewrites valuation or closes accounts."""
from decimal import Decimal
from hashlib import sha256

from Model.containermgmt.Inventory.CostPool import InventoryCostPool, BranchCostPool
from Model.containermgmt.Inventory.CostReconciliation import InventoryCostReconciliation
from Model.containermgmt.Inventory.Location import InventoryBranch
from Model.containermgmt.Inventory.StockLedger import StockBalance
from Model.containermgmt.Inventory.Valuation import InventoryValuation
from Model.containermgmt.Orders.Product import Product
from Services.inventory_posting_service import execute_once, PostingEffect, PostingConflict, _json_snapshot
from Services.manager_case_service import CaseBinding, consume_case
from Services.posting_authority_service import CostPoolAuthorityClaim, require_cost_pool_authority
from Utils.org_filter import apply_org_filter


ACTION = "inventory.cost.reconcile-product"


def _owned(db, model, context):
    return apply_org_filter(db.query(model).filter(
        model.org_id == context.org_id, model.is_deleted.is_(False)), model, context)


def reconciliation_binding(db, context, cost_pool_id, product_id, *, lock=True):
    if context.org_id not in context.allowed_org_ids:
        raise PermissionError("Cost reconciliation company denied")
    if type(cost_pool_id) is not int or cost_pool_id <= 0 or type(product_id) is not int or product_id <= 0:
        raise ValueError("Positive pool and product identities required")
    pool_query = _owned(db, InventoryCostPool, context).filter_by(id=cost_pool_id, is_active=True)
    product_query = _owned(db, Product, context).filter_by(
        id=product_id, status="active", is_shared=False).with_entities(
            Product.id, Product.name)
    if lock:
        pool_query = pool_query.with_for_update()
        product_query = product_query.with_for_update(of=Product)
    pool = pool_query.one_or_none()
    product = product_query.one_or_none()
    if pool is None or product is None:
        raise LookupError("Active reconciliation scope not found")
    branches = _owned(db, BranchCostPool, context).join(InventoryBranch,
        (InventoryBranch.id == BranchCostPool.branch_id) &
        (InventoryBranch.org_id == BranchCostPool.org_id)).filter(
            BranchCostPool.cost_pool_id == cost_pool_id,
            InventoryBranch.is_active.is_(True),
            InventoryBranch.is_deleted.is_(False)).with_entities(
                BranchCostPool.branch_id).order_by(BranchCostPool.branch_id).all()
    branch_ids = [row.branch_id for row in branches]
    if not branch_ids:
        raise ValueError("Cost pool has no active branch mapping")
    balance_query = _owned(db, StockBalance, context).filter(
        StockBalance.branch_id.in_(branch_ids), StockBalance.product_id == product_id).order_by(StockBalance.id)
    if lock:
        balance_query = balance_query.with_for_update()
    balances = balance_query.all()
    if not balances:
        raise ValueError("No physical stock scope exists for reconciliation")
    head_query = _owned(db, InventoryValuation, context).filter_by(
        cost_pool_id=cost_pool_id, product_id=product_id).order_by(
            InventoryValuation.version.desc(), InventoryValuation.id.desc())
    if lock:
        head_query = head_query.with_for_update()
    head = head_query.first()
    if head is None:
        raise ValueError("Latest inventory valuation is required")
    units = {row.base_unit for row in balances}
    if units != {head.base_unit}:
        raise PostingConflict("Physical and valuation base units differ")
    physical = sum((Decimal(row.on_hand) for row in balances), Decimal("0"))
    if physical != Decimal(head.pool_quantity):
        raise PostingConflict("Physical and valuation quantities must agree before reconciliation")
    lines = [{
        "balance_id": row.id, "branch_id": row.branch_id,
        "location_id": row.location_id, "version": row.version,
        "on_hand": format(row.on_hand, ".6f"),
        "reserved": format(row.reserved, ".6f"),
        "damaged": format(row.damaged, ".6f"),
        "quarantined": format(row.quarantined, ".6f"),
    } for row in balances]
    return CaseBinding(org_id=context.org_id, action=ACTION,
        source_type="inventory.cost-pool-product",
        source_key=f"{cost_pool_id}:{product_id}", source_version=head.version,
        details={
            "cost_pool_id": cost_pool_id, "product_id": product_id,
            "product_name": product.name, "valuation_id": head.id,
            "valuation_version": head.version, "base_unit": head.base_unit,
            "pool_quantity": format(head.pool_quantity, ".6f"),
            "pool_value_scr": format(head.pool_value_scr, ".6f"),
            "balances": lines,
        })


def close_reconciliation(db, context, actor_id, operation_key, *, case_key,
                         binding, authority_claim, authorize):
    if not isinstance(binding, CaseBinding) or binding.action != ACTION:
        raise ValueError("Exact cost reconciliation binding required")
    if not isinstance(authority_claim, CostPoolAuthorityClaim):
        raise PermissionError("Trusted central cost authority required")
    details = binding.details
    if authority_claim.org_id != context.org_id or authority_claim.cost_pool_id != details["cost_pool_id"]:
        raise PermissionError("Cost authority does not own this reconciliation scope")
    if not callable(authorize):
        raise PermissionError("Cost reconciliation authorization required")
    snapshot, encoded = _json_snapshot(binding.snapshot())
    digest = sha256(encoded.encode("utf-8")).hexdigest()
    request = {"case_key": str(case_key), "binding": snapshot,
        "authority": {"org_id": authority_claim.org_id,
            "cost_pool_id": authority_claim.cost_pool_id,
            "node_key": str(authority_claim.node_key), "epoch": authority_claim.epoch}}

    def current(session):
        authorize(session)
        require_cost_pool_authority(session, context, authority_claim,
                                    cost_pool_id=details["cost_pool_id"])
        loaded = reconciliation_binding(session, context,
            details["cost_pool_id"], details["product_id"], lock=True)
        if loaded.snapshot() != binding.snapshot():
            raise PostingConflict("Reconciliation source changed; request a new review")
        return loaded

    def guard(session):
        current(session)

    def apply(session):
        consume_case(session, context, actor_id, operation_key,
            case_key=case_key, binding=binding, load_binding=current,
            authorize=lambda active: authorize(active))
        if _owned(session, InventoryCostReconciliation, context).filter_by(
                cost_pool_id=details["cost_pool_id"], product_id=details["product_id"],
                source_digest=digest).first():
            raise PostingConflict("This exact cost state is already reconciled")
        row = InventoryCostReconciliation(org_id=context.org_id,
            checkpoint_key=operation_key, cost_pool_id=details["cost_pool_id"],
            product_id=details["product_id"], valuation_id=details["valuation_id"],
            valuation_version=details["valuation_version"],
            line_count=len(details["balances"]), base_unit=details["base_unit"],
            pool_quantity=Decimal(details["pool_quantity"]),
            pool_value_scr=Decimal(details["pool_value_scr"]),
            source_digest=digest, snapshot=snapshot, status="CLOSED", created_by=actor_id)
        session.add(row); session.flush()
        result = {"checkpoint_key": str(operation_key),
            "cost_pool_id": row.cost_pool_id, "product_id": row.product_id,
            "valuation_id": row.valuation_id, "valuation_version": row.valuation_version,
            "pool_quantity": details["pool_quantity"],
            "pool_value_scr": details["pool_value_scr"], "status": "CLOSED"}
        return PostingEffect(result, {"kind": "inventory.cost.reconciliation-closed",
            "checkpoint_key": str(operation_key), "cost_pool_id": row.cost_pool_id,
            "product_id": row.product_id, "valuation_version": row.valuation_version})

    return execute_once(db, context, actor_id, operation_key,
        "inventory.cost.reconciliation-close.v1", request, apply, authorize=guard)

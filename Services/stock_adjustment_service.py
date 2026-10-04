"""Exact manager-case binding for one location/batch stock correction."""
from decimal import Decimal

from Model.containermgmt.Inventory.Location import InventoryBranch, StockLocation
from Model.containermgmt.Inventory.StockLedger import StockBalance, StockMovement
from Model.containermgmt.Orders.Product import Product
from Schema.InventoryPolicySchema import InventoryPolicyConfig
from Services.inventory_quantity_service import QuantityBreakdown
from Services.inventory_unit_service import convert_quantity
from Services.manager_case_service import CaseBinding
from Utils.org_filter import apply_org_filter


def _query(db, model, context):
    return apply_org_filter(db.query(model).filter(
        model.org_id == context.org_id,
        model.is_deleted.is_(False),
    ), model, context)


def load_stock_adjustment_binding(db, context, balance_id, target_on_hand,
                                  target_damaged, target_quarantined, *, lock=True):
    if context.org_id not in context.allowed_org_ids:
        raise PermissionError("Stock adjustment company denied")
    if type(balance_id) is not int or balance_id <= 0:
        raise ValueError("Positive stock balance identity required")
    query = _query(db, StockBalance, context).filter(StockBalance.id == balance_id)
    if lock:
        query = query.populate_existing().with_for_update()
    balance = query.one_or_none()
    if balance is None:
        raise LookupError("Stock balance not found")
    if balance.tracking_policy not in ("UNTRACKED", "BATCH"):
        raise ValueError("Serial stock adjustments require exact serial-identity workflow")
    if balance.policy_config is None:
        raise ValueError("Stock policy requires review before adjustment")
    branch = _query(db, InventoryBranch, context).filter_by(
        id=balance.branch_id, is_active=True).one_or_none()
    location = _query(db, StockLocation, context).filter_by(
        id=balance.location_id, branch_id=balance.branch_id, is_active=True).one_or_none()
    product = _query(db, Product, context).filter_by(
        id=balance.product_id, status="active", is_shared=False).one_or_none()
    if branch is None or location is None or product is None:
        raise LookupError("Active stock scope not found")
    policy = InventoryPolicyConfig.model_validate(balance.policy_config)
    target = QuantityBreakdown(
        Decimal(target_on_hand), Decimal(balance.reserved),
        Decimal(target_damaged), Decimal(target_quarantined),
    )
    for value in (target.on_hand, target.damaged, target.quarantined):
        convert_quantity(policy, value, balance.base_unit, allow_zero=True)
    before = QuantityBreakdown(
        Decimal(balance.on_hand), Decimal(balance.reserved),
        Decimal(balance.damaged), Decimal(balance.quarantined),
    )
    if target == before:
        raise ValueError("Stock adjustment must change a physical quantity")
    return CaseBinding(
        org_id=context.org_id,
        action="inventory.stock.adjust",
        source_type="inventory.stock-balance",
        source_key=str(balance.id),
        source_version=balance.version,
        details={
            "balance_id": balance.id,
            "branch_id": balance.branch_id,
            "location_id": balance.location_id,
            "product_id": balance.product_id,
            "product_name": product.name,
            "base_unit": balance.base_unit,
            "tracking_policy": balance.tracking_policy,
            "batch_key": str(balance.batch_key) if balance.batch_key else None,
            "before_on_hand": format(before.on_hand, ".6f"),
            "reserved": format(before.reserved, ".6f"),
            "before_damaged": format(before.damaged, ".6f"),
            "before_quarantined": format(before.quarantined, ".6f"),
            "target_on_hand": format(target.on_hand, ".6f"),
            "target_damaged": format(target.damaged, ".6f"),
            "target_quarantined": format(target.quarantined, ".6f"),
        },
    )


def reload_stock_adjustment_binding(db, context, binding, *, replay_operation=None):
    details = binding.details
    if replay_operation is not None:
        movement = _query(db, StockMovement, context).filter_by(
            operation_key=replay_operation,
            balance_id=details["balance_id"],
            kind="ADJUSTMENT",
            version=binding.source_version + 1,
        ).one_or_none()
        if movement is not None and (
            format(movement.on_hand, ".6f") == details["target_on_hand"]
            and format(movement.reserved, ".6f") == details["reserved"]
            and format(movement.damaged, ".6f") == details["target_damaged"]
            and format(movement.quarantined, ".6f") == details["target_quarantined"]
        ):
            return binding
    return load_stock_adjustment_binding(
        db, context, details["balance_id"], details["target_on_hand"],
        details["target_damaged"], details["target_quarantined"], lock=True,
    )


"""Append exact receipt value inside a future atomic receipt coordinator.

The caller supplies a server-reviewed SCR goods value. This module never resolves
foreign exchange, accepts additional landed cost, commits, or exposes a route.
"""
from decimal import Decimal
from uuid import UUID
from sqlalchemy import func, tuple_
from Model.containermgmt.Inventory.ReceiptManifest import InventoryReceiptManifestRecord
from Model.containermgmt.Inventory.ReceiptSourceUse import InventoryReceiptSourceUse
from Model.containermgmt.Inventory.StockLedger import StockBalance, StockMovement
from Model.containermgmt.Inventory.CostPool import BranchCostPool
from Model.containermgmt.Inventory.Valuation import InventoryValuation
from Model.containermgmt.Orders.Product import Product
from Services.inventory_costing_service import (
    COSTING_POLICY_VERSION, CostBalance, CostPool, allocate_additional_cost, receive)
from Services.inventory_posting_service import PostingConflict
from Services.posting_authority_service import (
    CostPoolAuthorityClaim, require_cost_pool_authority)
from Utils.org_filter import apply_org_filter


ZERO = Decimal('0.000000')


def _owned(db, model, context):
    return apply_org_filter(db.query(model).filter(
        model.org_id == context.org_id, model.is_deleted.is_(False)), model, context)


def check_receipt_value(db, context, *, manifest_key, authority, authorize):
    """Acquire central pool authority before any receipt/source locks."""
    if not db.in_transaction() or not callable(authorize):
        raise ValueError('Receipt valuation requires an active transaction and permission guard')
    authorize(db)
    if not isinstance(authority, CostPoolAuthorityClaim) or authority.org_id != context.org_id:
        raise PermissionError('Trusted central cost-pool claim required')
    record = _owned(db, InventoryReceiptManifestRecord, context).filter_by(
        manifest_key=manifest_key).one_or_none()
    if record is None:
        raise LookupError('Receipt manifest not found')
    try:
        branch_id = record.snapshot['source']['branch_id']
        product_id = record.snapshot['source']['product_id']
    except (KeyError, TypeError):
        raise PostingConflict('Receipt manifest has an invalid valuation scope') from None
    if any(type(value) is not int or value <= 0 for value in (branch_id, product_id)):
        raise PostingConflict('Receipt manifest has an invalid valuation scope')
    require_cost_pool_authority(db, context, authority,
        cost_pool_id=authority.cost_pool_id)
    mapping = _owned(db, BranchCostPool, context).filter_by(
        branch_id=branch_id, cost_pool_id=authority.cost_pool_id).with_for_update(
            read=True).one_or_none()
    if mapping is None:
        raise PermissionError('Receipt branch is outside central cost-pool authority')
    return dict(branch_id=branch_id, product_id=product_id,
        cost_pool_id=authority.cost_pool_id)


def append_receipt_values(db, context, actor_id, operation_key, *, manifest_key,
        expected_version, goods_value_scr, reason, authority, authorize):
    """Add one valuation row per receipt movement without owning the transaction."""
    if not db.in_transaction() or not callable(authorize):
        raise ValueError('Receipt valuation requires an active outer transaction and permission guard')
    if type(actor_id) is not int or actor_id <= 0:
        raise ValueError('Authenticated receipt valuation actor required')
    if not isinstance(operation_key, UUID) or not operation_key.int:
        raise ValueError('Stable nonzero receipt operation identity required')
    if type(expected_version) is not int or expected_version < 0:
        raise ValueError('Expected valuation version must be nonnegative')
    if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 500:
        raise ValueError('A bounded receipt valuation reason is required')
    scope = check_receipt_value(db, context, manifest_key=manifest_key,
        authority=authority, authorize=authorize)
    source = _owned(db, InventoryReceiptSourceUse, context).filter_by(
        operation_key=operation_key, manifest_key=manifest_key,
        created_by=actor_id).one_or_none()
    if source is None:
        raise PermissionError('Receipt valuation requires source consumption in this operation')
    # This validates finite exact SCR input before it can enter the stream. The
    # future coordinator must obtain it from reviewed currency/cost evidence.
    receive(CostBalance(CostPool(context.org_id, scope['cost_pool_id'],
        scope['product_id']), ZERO, ZERO), source.quantity, goods_value_scr, ZERO)
    rows = _owned(db, StockMovement, context).join(StockBalance,
        (StockBalance.id == StockMovement.balance_id) &
        (StockBalance.org_id == StockMovement.org_id)).filter(
            StockMovement.operation_key == operation_key,
            StockMovement.kind == 'RECEIPT').order_by(
                StockMovement.balance_id, StockMovement.version).with_entities(
                    StockMovement, StockBalance).all()
    if not rows or sum((row.on_hand_delta for row, _ in rows), ZERO) != source.quantity:
        raise PostingConflict('Receipt valuation requires the complete source-bound movement set')
    if any(balance.branch_id != scope['branch_id'] or
            balance.product_id != scope['product_id'] or
            balance.base_unit != source.base_unit for _, balance in rows):
        raise PostingConflict('Receipt movement set differs from its valuation scope')
    product = _owned(db, Product, context).filter_by(id=scope['product_id'],
        status='active', is_shared=False).with_for_update(of=Product).one_or_none()
    if product is None:
        raise PermissionError('Receipt valuation product unavailable')
    latest = _owned(db, InventoryValuation, context).filter_by(
        cost_pool_id=scope['cost_pool_id'], product_id=scope['product_id']).order_by(
            InventoryValuation.version.desc()).first()
    version = latest.version if latest else 0
    if version != expected_version:
        raise PostingConflict('Valuation version changed; refresh before posting')
    if latest is not None and latest.base_unit != source.base_unit:
        raise PostingConflict('Valuation base unit differs from the receipt source')
    physical = _owned(db, StockBalance, context).join(BranchCostPool,
        (BranchCostPool.branch_id == StockBalance.branch_id) &
        (BranchCostPool.org_id == StockBalance.org_id)).filter(
            BranchCostPool.cost_pool_id == scope['cost_pool_id'],
            BranchCostPool.is_deleted.is_(False),
            StockBalance.product_id == scope['product_id']).with_entities(
                func.coalesce(func.sum(StockBalance.on_hand), 0)).scalar()
    physical_before = Decimal(physical) - source.quantity
    valued_before = latest.pool_quantity if latest else ZERO
    if physical_before != valued_before:
        raise PostingConflict('Unvalued physical stock blocks receipt valuation')
    sources = [(balance.id, movement.version) for movement, balance in rows]
    existing = _owned(db, InventoryValuation, context).filter(
        tuple_(InventoryValuation.balance_id, InventoryValuation.source_version).in_(sources),
        InventoryValuation.kind.in_(('OPENING', 'RECEIPT'))).first()
    if existing is not None:
        raise PostingConflict('Receipt movement already has a valuation')
    keys = {f'{movement.balance_id}:{movement.version}': movement.on_hand_delta
        for movement, _ in rows}
    allocations = allocate_additional_cost(goods_value_scr, keys)
    before = CostBalance(CostPool(context.org_id, scope['cost_pool_id'],
        scope['product_id']), valued_before, latest.pool_value_scr if latest else ZERO)
    valuation_ids = []
    for movement, balance in rows:
        key = f'{movement.balance_id}:{movement.version}'
        value = allocations[key]
        after = receive(before, movement.on_hand_delta, value, ZERO)
        row = InventoryValuation(org_id=context.org_id, kind='RECEIPT',
            source_valuation_id=None, operation_key=operation_key,
            cost_pool_id=scope['cost_pool_id'], product_id=scope['product_id'],
            balance_id=balance.id, source_version=movement.version,
            version=version + 1, base_unit=source.base_unit,
            quantity=movement.on_hand_delta, goods_value_scr=value,
            additional_cost_scr=ZERO, pool_quantity=after.quantity,
            pool_value_scr=after.value_scr, calculation_policy=COSTING_POLICY_VERSION,
            currency='SCR', status='UNRECONCILED', reason=reason.strip(),
            created_by=actor_id)
        db.add(row); db.flush()
        valuation_ids.append(row.id)
        version += 1
        before = after
    return dict(valuation_ids=valuation_ids, cost_pool_id=scope['cost_pool_id'],
        product_id=scope['product_id'], version=version,
        pool_quantity=format(before.quantity, '.6f'),
        pool_value_scr=format(before.value_scr, '.6f'),
        average_cost_scr=format(before.average_cost_scr, '.6f'),
        status='UNRECONCILED')

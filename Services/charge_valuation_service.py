"""Append allocated costs inside an already-authorized, caller-owned transaction.

No commit/receipt, prices, stock movement or public posting. The coordinator must
consume charge and evidence case in this transaction first; database guards enforce
those links. Later issued-stock costs require their own expense adjustment design.
"""
from decimal import Decimal, localcontext
from uuid import UUID
from Model.containermgmt.Inventory.Valuation import InventoryValuation
from Model.containermgmt.Inventory.CostChargeUse import CostChargeUse
from Model.containermgmt.Inventory.CostAllocation import CostAllocationProposal
from Model.containermgmt.Inventory.StockLedger import StockBalance, StockMovement
from Model.containermgmt.Orders.Product import Product
from Services.inventory_costing_service import MAX_VALUE
from Services.inventory_posting_service import PostingConflict
from Utils.org_filter import apply_org_filter


def append_allocated_charge_values(db, context, actor_id, operation_key, *, expected_versions, authorize):
    if not db.in_transaction() or not callable(authorize):
        raise ValueError('Active transaction and explicit central-authority/permission guard required')
    authorize(db)
    if context.org_id not in context.allowed_org_ids:
        raise PermissionError('Valuation company scope denied')
    if type(actor_id) is not int or actor_id <= 0 or not isinstance(operation_key, UUID) or not operation_key.int:
        raise ValueError('Authenticated actor and nonzero operation key required')
    charge = apply_org_filter(db.query(CostChargeUse).filter_by(org_id=context.org_id,
        operation_key=operation_key, created_by=actor_id, is_deleted=False), CostChargeUse, context).one_or_none()
    if charge is None: raise PermissionError('This operation has not consumed its verified charge')
    proposal = apply_org_filter(db.query(CostAllocationProposal).filter_by(org_id=context.org_id,
        proposal_key=charge.proposal_key, is_deleted=False), CostAllocationProposal, context).one()
    lines = proposal.snapshot['lines']
    ids = [line['valuation_id'] for line in lines]
    if not 1 <= len(ids) <= 100 or len(set(ids)) != len(ids): raise ValueError('Bounded distinct allocation sources required')
    sources = apply_org_filter(db.query(InventoryValuation).filter(InventoryValuation.org_id == context.org_id,
        InventoryValuation.id.in_(ids), InventoryValuation.kind == 'OPENING', InventoryValuation.is_deleted.is_(False)),
        InventoryValuation, context).all()
    products = sorted({row.product_id for row in sources})
    if len(sources) != len(ids) or set(expected_versions) != set(products):
        raise PostingConflict('Exact source set and expected product stream versions required')
    if any(type(value) is not int or value < 1 for value in expected_versions.values()):
        raise ValueError('Positive expected stream versions required')
    # Same deterministic product lock as opening valuation, before reading latest.
    locked = apply_org_filter(db.query(Product.id).filter(Product.org_id == context.org_id,
        Product.id.in_(products), Product.is_deleted.is_(False), Product.is_shared.is_(False)),
        Product, context).order_by(Product.id).with_for_update().all()
    if len(locked) != len(products): raise PermissionError('Valuation product unavailable')
    latest = {}
    for product in products:
        row = apply_org_filter(db.query(InventoryValuation).filter_by(org_id=context.org_id,
            cost_pool_id=proposal.cost_pool_id, product_id=product, is_deleted=False), InventoryValuation, context).order_by(InventoryValuation.version.desc()).first()
        if row is None or row.version != expected_versions[product]: raise PostingConflict('Valuation stream changed')
        latest[product] = row
    sources = {row.id: row for row in sources}
    result = []
    with localcontext() as arithmetic:
        arithmetic.prec = 60
        if sum((Decimal(line['allocated_scr']) for line in lines), Decimal(0)) != charge.amount_scr:
            raise PostingConflict('Charge allocation must conserve the complete charge')
        for line in sorted(lines, key=lambda item: (item['product_id'], item['valuation_id'])):
            source = sources[line['valuation_id']]
            if source.cost_pool_id != proposal.cost_pool_id or source.product_id != line['product_id'] or source.balance_id != line['balance_id']:
                raise PostingConflict('Allocation source scope mismatch')
            balance = apply_org_filter(db.query(StockBalance).filter_by(id=source.balance_id,
                org_id=context.org_id, is_deleted=False), StockBalance, context).populate_existing().with_for_update().one()
            moved = apply_org_filter(db.query(StockMovement.id).filter(
                StockMovement.org_id == context.org_id, StockMovement.balance_id == balance.id,
                StockMovement.version > source.source_version, StockMovement.on_hand_delta != 0),
                StockMovement, context).first()
            if balance.on_hand != source.quantity or moved is not None:
                raise PostingConflict('Changed physical stock requires a late-cost reconciliation workflow')
            before = latest[source.product_id]; amount = Decimal(line['allocated_scr'])
            if amount < 0 or before.pool_value_scr + amount > MAX_VALUE:
                raise ValueError('Allocated cost outside valuation bounds')
            row = InventoryValuation(org_id=context.org_id, kind='CHARGE', source_valuation_id=source.id,
                operation_key=operation_key, cost_pool_id=source.cost_pool_id, product_id=source.product_id,
                balance_id=source.balance_id, source_version=source.source_version, version=before.version + 1,
                base_unit=source.base_unit, quantity=Decimal(0), goods_value_scr=Decimal(0), additional_cost_scr=amount,
                pool_quantity=before.pool_quantity, pool_value_scr=before.pool_value_scr + amount,
                calculation_policy=source.calculation_policy, currency='SCR', status='UNRECONCILED',
                reason='Approved additional-cost allocation', created_by=actor_id)
            db.add(row); db.flush(); latest[source.product_id] = row
            result.append(row.id)
    return result

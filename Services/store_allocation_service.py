"""Internal store-wide allocation; no client-supplied authority or public writer.

The caller's guard must authorise the working store independently of the counter.
Counter preference never grants stock access. Existing holds are protected; this
initial-allocation operation does not top up or replace them (reviewed lifecycle).
"""
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal, Context, localcontext
from uuid import uuid5
from sqlalchemy import case, select, or_
from sqlalchemy.orm import aliased

from Model.containermgmt.Inventory.Location import StockLocation
from Model.containermgmt.Inventory.StockLedger import StockBalance, StockBatch, StockReservation
from Model.containermgmt.Orders.Product import Product
from Schema.SalesReservationSchema import SalesDemandReference
from Schema.InventoryPolicySchema import InventoryPolicyConfig
from Services.default_stock_area_service import require_default_stock_area, stock_area_locations, require_owned_stock_area
from Services.branch_action_context_service import BranchActionContext
from Services.inventory_posting_service import execute_once, PostingEffect, PostingConflict
from Services.inventory_unit_service import convert_quantity
from Services.policy_activation_service import active_policy
from Services.policy_compatibility_service import extends_policy
from Services.posting_authority_service import AuthorityClaim, require_posting_authority
from Services.sales_reservation_source_service import owned, load_reservation_demand
from Services.staff_store_assignment_service import require_staff_store_assignment
from Services.stock_ledger_service import reserve_stock, _snapshot, _positive, _reason


def eligible_store_balances(db, context, branch_id, product_id, business_date):
    """Scoped product-index query; active ancestry and expiry before planning."""
    zone, site = aliased(StockLocation), aliased(StockLocation)
    sites = select(site.id).where(site.org_id == context.org_id, site.branch_id == branch_id,
        site.is_active.is_(True), site.is_deleted.is_(False), site.kind == 'SITE', site.parent_id.is_(None))
    zones = select(zone.id).where(zone.org_id == context.org_id, zone.branch_id == branch_id,
        zone.is_active.is_(True), zone.is_deleted.is_(False), zone.kind == 'ZONE', zone.parent_id.in_(sites))
    locations = select(StockLocation.id).where(StockLocation.org_id == context.org_id,
        StockLocation.branch_id == branch_id, StockLocation.is_active.is_(True), StockLocation.is_deleted.is_(False),
        or_(StockLocation.id.in_(sites), StockLocation.id.in_(zones),
            (StockLocation.kind == 'BIN') & StockLocation.parent_id.in_(zones)))
    return owned(db, StockBalance, context).outerjoin(StockBatch,
        (StockBatch.batch_key == StockBalance.batch_key) & (StockBatch.product_id == StockBalance.product_id) &
        (StockBatch.org_id == StockBalance.org_id)).filter(
        StockBalance.branch_id == branch_id, StockBalance.product_id == product_id,
        StockBalance.location_id.in_(locations), StockBalance.policy_config.isnot(None),
        StockBalance.on_hand > StockBalance.reserved + StockBalance.damaged + StockBalance.quarantined,
        or_(StockBalance.batch_key.is_(None), (StockBatch.is_deleted.is_(False) &
            or_(StockBatch.expires_on.is_(None), StockBatch.expires_on >= business_date))))


def allocate_store_stock(factory, context, actor_id, operation_key, *, source, action_context,
                         quantity, input_unit, review_at, reason, authority, authorize, assignment_version):
    """All-or-nothing initial hold, compatible batch, preferred area then same store.

    Shared receipts group deterministic child reservations. No separate ledger,
    guessed staff assignment, cross-store fallback or silent partial allocation.
    Trusted adapters must rebuild action_context/permissions on every attempt.
    """
    if (not isinstance(source, SalesDemandReference) or not isinstance(authority, AuthorityClaim)
            or not isinstance(action_context, BranchActionContext)):
        raise ValueError('Typed source, trusted action context and authority required')
    _positive(quantity); _reason(reason)
    if not isinstance(review_at, datetime) or review_at.utcoffset() is None:
        raise ValueError('Review time must include timezone')
    state = {}

    def guard(db):
        if not callable(authorize): raise ValueError('Working-store permission guard required')
        require_posting_authority(db, context, authority, branch_id=action_context.branch_id)
        authorize(db)
        require_staff_store_assignment(db, context, actor_id, branch_id=action_context.branch_id,
            expected_version=assignment_version)
        state['root'] = require_default_stock_area(db, context, action_context)
        revision, line = load_reservation_demand(db, context, source)
        if revision.branch_id != action_context.branch_id: raise PostingConflict('Another store requires explicit fulfilment approval')
        base = convert_quantity(InventoryPolicyConfig.model_validate(line.policy), quantity, input_unit)
        if base > line.base_quantity: raise PostingConflict('Hold exceeds saved line quantity')
        product = owned(db, Product, context).filter_by(id=line.product_id, status='active', is_shared=False).with_entities(Product.id).with_for_update(of=Product).one_or_none()
        if product is None: raise LookupError('Active selling product not found')
        state.update(line=line, quantity=base)

    def apply(db):
        if owned(db, StockReservation, context).filter_by(source_line_key=source.stock_source_key()).first():
            raise PostingConflict('Existing reservation history requires the reviewed lifecycle, not initial allocation')
        line, base, root = state['line'], state['quantity'], state['root']
        query = eligible_store_balances(db, context, action_context.branch_id, line.product_id, action_context.business_date)
        preferred = StockBalance.location_id.in_(stock_area_locations(db, context, root).with_entities(StockLocation.id).statement) if root else StockBalance.id < 0
        active = active_policy(db, context, line.product_id)
        # Stream candidates; retain at most the requested quantity per compatible lot.
        # A preferred lot which cannot satisfy demand must not mask a sufficient lot.
        groups = {}
        for balance in query.order_by(case((preferred, 0), else_=1), StockBalance.id).yield_per(100):
            if active and not extends_policy(balance.policy_config, active.config): continue
            policy = InventoryPolicyConfig.model_validate(active.config if active else balance.policy_config)
            if policy.base_unit != line.base_unit: continue
            key = (balance.batch_key, balance.tracking_policy, balance.base_unit)
            rows, total = groups.setdefault(key, ([], Decimal(0)))
            if total >= base: continue
            with localcontext(Context(prec=48)):
                take = min(_snapshot(balance).available, base - total)
                convert_quantity(policy, take, balance.base_unit)
                rows.append((balance.id, balance.location_id, take))
                groups[key] = rows, total + take
        plan = next((rows for rows, total in groups.values() if total >= base), None)
        if plan is None: raise PostingConflict('Insufficient compatible stock in this store; choose an explicit alternative or review demand')
        # Stable stock-lock order independent of a counter's preference.
        children = []
        for balance_id, location_id, take in sorted(plan):
            require_owned_stock_area(db, context, action_context.branch_id, location_id)
            child = uuid5(operation_key, f'reserve:{balance_id}')
            hold = uuid5(operation_key, f'hold:{balance_id}')
            reserve_stock(db, context, actor_id, child, balance_id=balance_id,
                reservation_key=hold, source_line_key=source.stock_source_key(), quantity=take,
                input_unit=line.base_unit, review_at=review_at, reason=reason,
                business_date=action_context.business_date, authority=authority, authorize=authorize, sales_source=source)
            children.append(dict(operation_key=str(child), reservation_key=str(hold), balance_id=balance_id,
                location_id=location_id, quantity=str(take)))
        return PostingEffect(dict(branch_id=action_context.branch_id, quantity=str(base), base_unit=line.base_unit,
            reservations=children), dict(kind='stock.store-allocation', child_operations=[r['operation_key'] for r in children]))

    action = asdict(action_context); action['business_date'] = action_context.business_date.isoformat()
    claim = asdict(authority); claim['node_key'] = str(authority.node_key)
    return execute_once(factory, context, actor_id, operation_key, 'stock.store-allocation.v1',
        dict(source=source.model_dump(mode='json'), action=action, authority=claim, assignment_version=assignment_version, quantity=str(quantity),
            input_unit=input_unit, review_at=review_at.isoformat(), reason=reason), apply, authorize=guard)

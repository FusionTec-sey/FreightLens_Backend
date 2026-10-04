"""Read-only local area quantities; no stock authority or reservation effect."""
from decimal import Decimal
from sqlalchemy import func, select
from Model.containermgmt.Inventory.BranchCounter import BranchCounter, CounterSettingsRevision
from Model.containermgmt.Inventory.Location import StockLocation
from Model.containermgmt.Inventory.StockLedger import StockBalance
from Schema.BranchCounterSchema import CounterConfig
from Services.default_stock_area_service import require_owned_stock_area
from Services.sales_intent_service import get_sales_intent
from Services.sales_local_reservation_service import runtime_claim
from Utils.org_filter import apply_org_filter


def preview_sales_area(db, context, document_key, counter_key, *, authorize):
    draft = get_sales_intent(db, context, document_key, authorize=authorize)
    counter = apply_org_filter(db.query(BranchCounter).filter_by(
        org_id=context.org_id, branch_id=draft['branch_id'], counter_key=counter_key,
        is_deleted=False), BranchCounter, context).one_or_none()
    if counter is None:
        raise LookupError('Counter not found in the selling store')
    revision = apply_org_filter(db.query(CounterSettingsRevision).filter_by(
        org_id=context.org_id, counter_id=counter.id, is_deleted=False),
        CounterSettingsRevision, context).order_by(CounterSettingsRevision.version.desc()).first()
    if revision is None:
        raise LookupError('Counter settings not found')
    config = CounterConfig.model_validate(revision.config)
    if not config.is_enabled or config.purpose not in ('CHECKOUT', 'BOTH'):
        raise PermissionError('Counter is not enabled for checkout')
    if config.default_stock_location_id is None:
        raise ValueError('Set a counter work area before previewing local stock')
    root = require_owned_stock_area(db, context, draft['branch_id'], config.default_stock_location_id)

    area = select(StockLocation.id).where(StockLocation.id == root.id).cte('work_area', recursive=True)
    area = area.union(select(StockLocation.id).join(area, StockLocation.parent_id == area.c.id).where(
        StockLocation.org_id == context.org_id, StockLocation.branch_id == draft['branch_id'],
        StockLocation.is_active.is_(True), StockLocation.is_deleted.is_(False)))
    scope = (StockBalance.org_id == context.org_id, StockBalance.branch_id == draft['branch_id'],
        StockBalance.is_deleted.is_(False), StockBalance.policy_config.isnot(None),
        StockBalance.product_id.in_([line['product_id'] for line in draft['lines']]))
    rows = apply_org_filter(db.query(StockBalance, StockLocation.name.label('location_name'))
        .select_from(StockBalance)
        .join(area, StockBalance.location_id == area.c.id).filter(
            *scope, StockBalance.tracking_policy == 'UNTRACKED')
        .join(StockLocation, (StockLocation.id == StockBalance.location_id) &
            (StockLocation.org_id == StockBalance.org_id)), StockBalance, context
        ).order_by(StockBalance.product_id, StockBalance.location_id, StockBalance.id).limit(501).all()
    incomplete = len(rows) > 500
    buckets = {}
    for balance, location_name in rows[:500]:
        quantity = balance.on_hand - balance.reserved - balance.damaged - balance.quarantined
        if quantity <= 0 or balance.quantity_step is None or balance.quantity_step <= 0:
            continue
        buckets.setdefault((balance.product_id, balance.base_unit), []).append(dict(
            balance_id=balance.id, balance_version=balance.version,
            location_id=balance.location_id, location_name=location_name,
            step=balance.quantity_step, remaining=quantity))
    available = func.sum(StockBalance.on_hand - StockBalance.reserved - StockBalance.damaged - StockBalance.quarantined)
    tracked_rows = apply_org_filter(db.query(StockBalance.product_id, StockBalance.base_unit, available.label('quantity'))
        .join(area, StockBalance.location_id == area.c.id).filter(
            *scope, StockBalance.tracking_policy.in_(('BATCH', 'SERIAL')))
        .group_by(StockBalance.product_id, StockBalance.base_unit), StockBalance, context).all()
    tracked = {(row.product_id, row.base_unit): row.quantity for row in tracked_rows}
    lines = []
    for line in draft['lines']:
        key = (line['product_id'], line['base_unit'])
        demand = max(Decimal(0), Decimal(line['base_quantity']) - Decimal(line['reserved_quantity']))
        local = sum((bucket['remaining'] for bucket in buckets.get(key, [])), Decimal(0))
        need = demand
        suggestions = []
        candidates = buckets.get(key, [])
        full = next((bucket for bucket in candidates if bucket['remaining'] >= need and need % bucket['step'] == 0), None) if need > 0 else None
        for bucket in ([full] if full else candidates):
            if need <= 0: break
            portion = min(need, bucket['remaining'])
            portion -= portion % bucket['step']
            if portion <= 0: continue
            suggestions.append(dict(balance_id=bucket['balance_id'], balance_version=bucket['balance_version'],
                location_id=bucket['location_id'], location_name=bucket['location_name'], quantity=format(portion, 'f')))
            bucket['remaining'] -= portion
            need -= portion
        coverage = demand - need
        lines.append(dict(line_key=line['line_key'], product_id=line['product_id'], base_unit=line['base_unit'],
            remaining_demand=format(demand, 'f'), local_unreserved=format(local, 'f'),
            provisional_coverage=format(coverage, 'f'), shortfall=format(need, 'f'),
            tracked_for_review=format(max(Decimal(0), tracked.get(key, Decimal(0))), 'f'),
            suggestions=suggestions))
    try:
        runtime_claim(db, context, draft['branch_id'])
        reservation_ready = True
    except PermissionError:
        reservation_ready = False
    return dict(document_key=draft['document_key'], draft_version=draft['version'],
        counter_key=counter_key, counter_version=revision.version,
        work_area_id=root.id, work_area_name=root.name, incomplete=incomplete,
        reservation_ready=reservation_ready, lines=lines)

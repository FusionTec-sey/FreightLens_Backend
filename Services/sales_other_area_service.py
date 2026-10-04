"""Exact reviewed exception for draft demand outside its selected counter area."""
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid5
from sqlalchemy import select
from Model.containermgmt.Inventory.BranchCounter import BranchCounter, CounterSettingsRevision
from Model.containermgmt.Inventory.Location import StockLocation
from Model.containermgmt.Inventory.StockLedger import StockBalance
from Model.containermgmt.Orders.SalesIntent import SalesIntent, SalesIntentRevision, SalesIntentLineRevision
from Schema.BranchCounterSchema import CounterConfig
from Schema.SalesReservationSchema import SalesDemandReference
from Services.default_stock_area_service import require_owned_stock_area
from Services.inventory_posting_service import PostingConflict
from Services.manager_case_service import CaseBinding
from Services.sales_local_reservation_service import scoped, runtime_claim
from Services.sales_reservation_source_service import active_demand_holds
from Services.stock_ledger_service import reserve_stock


ACTION = 'inventory.reservation.other-area'


def _source(db, context, document_key, version, line_key, counter_key, counter_version):
    parent = scoped(db, SalesIntent, context).filter_by(document_key=document_key).with_for_update().one_or_none()
    if parent is None: raise LookupError('Sales draft not found')
    draft = scoped(db, SalesIntentRevision, context).filter_by(document_key=document_key).order_by(
        SalesIntentRevision.version.desc()).first()
    if draft is None or draft.version != version or draft.status != 'DRAFT':
        raise PostingConflict('Sales draft changed; request a new approval')
    line = scoped(db, SalesIntentLineRevision, context).filter_by(document_key=document_key,
        version=version, line_key=line_key).one_or_none()
    if line is None: raise LookupError('Sales draft line not found')
    counter = scoped(db, BranchCounter, context).filter_by(branch_id=draft.branch_id,
        counter_key=counter_key).with_for_update().one_or_none()
    if counter is None: raise LookupError('Selling counter not found')
    revision = scoped(db, CounterSettingsRevision, context).filter_by(counter_id=counter.id).order_by(
        CounterSettingsRevision.version.desc()).first()
    if revision is None or revision.version != counter_version:
        raise PostingConflict('Counter settings changed; request a new approval')
    config = CounterConfig.model_validate(revision.config)
    if not config.is_enabled or config.purpose not in ('CHECKOUT', 'BOTH') or config.default_stock_location_id is None:
        raise PermissionError('Checkout counter work area is not enabled')
    root = require_owned_stock_area(db, context, draft.branch_id, config.default_stock_location_id)
    return draft, line, root


def outside_balances(db, context, document_key, version, line_key, counter_key, counter_version, page, limit):
    draft, line, root = _source(db, context, document_key, version, line_key, counter_key, counter_version)
    area = select(StockLocation.id).where(StockLocation.id == root.id).cte('other_area_scope', recursive=True)
    area = area.union(select(StockLocation.id).join(area, StockLocation.parent_id == area.c.id).where(
        StockLocation.org_id == context.org_id, StockLocation.branch_id == draft.branch_id,
        StockLocation.is_active.is_(True), StockLocation.is_deleted.is_(False)))
    available = StockBalance.on_hand - StockBalance.reserved - StockBalance.damaged - StockBalance.quarantined
    query = scoped(db, StockBalance, context).join(StockLocation,
        (StockLocation.id == StockBalance.location_id) & (StockLocation.org_id == StockBalance.org_id)).filter(
        StockBalance.product_id == line.product_id, StockBalance.base_unit == line.base_unit,
        StockBalance.tracking_policy == 'UNTRACKED', StockBalance.policy_config.isnot(None),
        StockLocation.is_active.is_(True), StockLocation.is_deleted.is_(False), available > 0,
        ~StockBalance.location_id.in_(select(area.c.id)))
    total = query.count()
    rows = query.order_by(StockBalance.branch_id, StockBalance.location_id, StockBalance.id).offset(
        (page - 1) * limit).limit(limit).with_entities(StockBalance, StockLocation.name).all()
    return dict(items=[dict(balance_id=balance.id, branch_id=balance.branch_id,
        location_name=name, available=format(balance.on_hand - balance.reserved - balance.damaged - balance.quarantined, 'f'),
        base_unit=balance.base_unit) for balance, name in rows], total=total, page=page,
        limit=limit, pages=max(1, (total + limit - 1) // limit))


def load_binding(db, context, *, document_key, version, line_key, counter_key, counter_version,
                 balance_id, quantity, review_at):
    draft, line, root = _source(db, context, document_key, version, line_key, counter_key, counter_version)
    balance = scoped(db, StockBalance, context).filter_by(id=balance_id).one_or_none()
    location = scoped(db, StockLocation, context).filter_by(id=balance.location_id,
        branch_id=balance.branch_id, is_active=True).one_or_none() if balance else None
    if (balance is None or location is None or balance.product_id != line.product_id
            or balance.base_unit != line.base_unit or balance.tracking_policy != 'UNTRACKED'
            or balance.policy_config is None):
        raise PostingConflict('Other-area stock no longer matches saved demand')
    if balance.branch_id == draft.branch_id:
        area = select(StockLocation.id).where(StockLocation.id == root.id).cte('other_area_check', recursive=True)
        area = area.union(select(StockLocation.id).join(area, StockLocation.parent_id == area.c.id).where(
            StockLocation.org_id == context.org_id, StockLocation.branch_id == draft.branch_id,
            StockLocation.is_active.is_(True), StockLocation.is_deleted.is_(False)))
        if db.query(area.c.id).filter(area.c.id == balance.location_id).first():
            raise PostingConflict('Selected stock is inside the normal counter area')
    amount = Decimal(quantity)
    if amount <= 0 or amount > line.base_quantity or balance.quantity_step is None or amount % balance.quantity_step:
        raise ValueError('Requested quantity must match the stock unit step and saved demand')
    if review_at.utcoffset() is None: raise ValueError('Review time needs a timezone')
    return CaseBinding(context.org_id, ACTION, 'sales.demand', f'{document_key}:{line_key}', draft.version,
        dict(document_key=str(document_key), line_key=str(line_key), counter_key=str(counter_key),
            counter_version=counter_version, work_area_id=root.id, selling_branch_id=draft.branch_id,
            target_branch_id=balance.branch_id, balance_id=balance.id, location_id=balance.location_id,
            product_id=line.product_id, base_unit=line.base_unit, quantity=format(amount, 'f'),
            review_at=review_at.isoformat()))


def reload_binding(db, context, binding):
    details = binding.details
    return load_binding(db, context, document_key=UUID(details['document_key']),
        version=binding.source_version, line_key=UUID(details['line_key']),
        counter_key=UUID(details['counter_key']), counter_version=details['counter_version'],
        balance_id=details['balance_id'], quantity=details['quantity'],
        review_at=datetime.fromisoformat(details['review_at']))


def execute_approved(db, context, actor_id, case, binding, *, authorize):
    details = binding.details
    if reload_binding(db, context, binding).snapshot() != binding.snapshot():
        raise PostingConflict('Approved stock request changed')
    claim = runtime_claim(db, context, details['target_branch_id'])
    source = SalesDemandReference(document_key=UUID(details['document_key']),
        line_key=UUID(details['line_key']), version=binding.source_version)
    operation_key = uuid5(case.case_key, 'other-area-reserve-operation-v1')
    reservation_key = uuid5(case.case_key, 'other-area-reserve-hold-v1')
    outcome = reserve_stock(db, context, actor_id, operation_key,
        balance_id=details['balance_id'], reservation_key=reservation_key,
        source_line_key=source.stock_source_key(), quantity=Decimal(details['quantity']),
        review_at=datetime.fromisoformat(details['review_at']), reason=case.reason,
        input_unit=details['base_unit'], authority=claim, authorize=authorize,
        sales_source=source, other_area_case=case.case_key, other_area_binding=binding,
        load_other_area_binding=lambda session: reload_binding(session, context, binding))
    return dict(reservation_key=reservation_key, balance_id=details['balance_id'],
        version=outcome.result['version'], replayed=outcome.replayed)

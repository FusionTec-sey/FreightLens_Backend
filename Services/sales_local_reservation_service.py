"""Explicit local draft hold through the guarded stock writer, never checkout."""
import os
from decimal import Decimal
from uuid import UUID, uuid5
from sqlalchemy import select
from Model.containermgmt.Inventory.BranchCounter import BranchCounter, CounterSettingsRevision
from Model.containermgmt.Inventory.Location import StockLocation
from Model.containermgmt.Inventory.PostingAuthority import StoreNode, BranchAuthorityEpoch
from Model.containermgmt.Inventory.PostingOperation import PostingOperation
from Model.containermgmt.Inventory.StockLedger import StockBalance
from Model.containermgmt.Orders.SalesIntent import SalesIntentRevision, SalesIntentLineRevision
from Schema.BranchCounterSchema import CounterConfig
from Schema.SalesReservationSchema import SalesDemandReference
from Services.default_stock_area_service import require_owned_stock_area
from Services.posting_authority_service import AuthorityClaim
from Services.stock_ledger_service import reserve_stock
from Services.inventory_posting_service import PostingConflict
from Services.sales_reservation_source_service import active_demand_holds
from Utils.org_filter import apply_org_filter


def scoped(db, model, context):
    return apply_org_filter(db.query(model).filter_by(org_id=context.org_id, is_deleted=False), model, context)


def runtime_claim(db, context, branch_id):
    """A process identity, never a value supplied by a browser request."""
    try:
        node_key = UUID(os.environ['STOCK_RUNTIME_NODE_KEY'])
    except (KeyError, ValueError) as error:
        raise PermissionError('Stock posting runtime is not configured') from error
    node = scoped(db, StoreNode, context).filter_by(node_key=node_key).one_or_none()
    epoch = scoped(db, BranchAuthorityEpoch, context).filter_by(branch_id=branch_id).order_by(
        BranchAuthorityEpoch.epoch.desc()).first()
    if node is None or epoch is None or epoch.state != 'ACTIVE' or epoch.node_id != node.id:
        raise PermissionError('This runtime does not own active stock authority for the store')
    return AuthorityClaim(context.org_id, branch_id, node_key, epoch.epoch)


def require_local_balance(db, context, draft, payload):
    counter = scoped(db, BranchCounter, context).filter_by(branch_id=draft.branch_id,
        counter_key=payload.counter_key).one_or_none()
    if counter is None: raise LookupError('Counter not found in the selling store')
    revision = scoped(db, CounterSettingsRevision, context).filter_by(counter_id=counter.id).order_by(
        CounterSettingsRevision.version.desc()).first()
    if revision is None or revision.version != payload.counter_version:
        raise PostingConflict('Counter settings changed; preview stock again')
    config = CounterConfig.model_validate(revision.config)
    if not config.is_enabled or config.purpose not in ('CHECKOUT', 'BOTH') or config.default_stock_location_id is None:
        raise PermissionError('Checkout counter or work area is not enabled')
    root = require_owned_stock_area(db, context, draft.branch_id, config.default_stock_location_id)
    area = select(StockLocation.id).where(StockLocation.id == root.id).cte('reserve_area', recursive=True)
    area = area.union(select(StockLocation.id).join(area, StockLocation.parent_id == area.c.id).where(
        StockLocation.org_id == context.org_id, StockLocation.branch_id == draft.branch_id,
        StockLocation.is_active.is_(True), StockLocation.is_deleted.is_(False)))
    balance = scoped(db, StockBalance, context).filter_by(id=payload.balance_id,
        branch_id=draft.branch_id, tracking_policy='UNTRACKED').filter(
        StockBalance.location_id.in_(select(area.c.id))).one_or_none()
    if balance is None: raise PostingConflict('Choose untracked stock inside the current counter work area')
    return balance


def reserve_local_draft(db, context, actor_id, document_key, payload, *, authorize):
    if not db.in_transaction(): raise ValueError('Active reservation transaction required')
    if context.org_id not in context.allowed_org_ids: raise PermissionError('Company denied')
    authorize(db)
    draft = scoped(db, SalesIntentRevision, context).filter_by(document_key=document_key).order_by(
        SalesIntentRevision.version.desc()).first()
    if draft is None: raise LookupError('Sales draft not found')
    if draft.version != payload.expected_draft_version or draft.status != 'DRAFT':
        raise PostingConflict('Sales draft changed; open the latest version')
    line = scoped(db, SalesIntentLineRevision, context).filter_by(document_key=document_key,
        version=draft.version, line_key=payload.line_key).one_or_none()
    if line is None: raise LookupError('Sales draft line not found')
    balance = require_local_balance(db, context, draft, payload)
    if balance.product_id != line.product_id or balance.base_unit != line.base_unit:
        raise PostingConflict('Suggested stock no longer matches draft demand')
    source = SalesDemandReference(document_key=document_key, line_key=line.line_key, version=draft.version)
    operation_key = uuid5(document_key, f'local-reserve-operation-v1:{line.line_key}:{draft.version}')
    reservation_key = uuid5(document_key, f'local-reserve-hold-v1:{line.line_key}:{draft.version}')
    receipt = scoped(db, PostingOperation, context).filter_by(operation_key=operation_key).one_or_none()
    if receipt is None:
        if active_demand_holds(db, context, document_key).get(line.line_key, Decimal(0)):
            raise PostingConflict('This draft line already has a stock hold')
        if Decimal(payload.quantity) != line.base_quantity:
            raise ValueError('Local automatic reservation requires the complete unheld draft line quantity')
    claim = runtime_claim(db, context, draft.branch_id)
    def guard(session):
        authorize(session)
        current = scoped(session, SalesIntentRevision, context).filter_by(document_key=document_key).order_by(
            SalesIntentRevision.version.desc()).first()
        if current is None or current.version != draft.version:
            raise PostingConflict('Sales draft changed; open the latest version')
        require_local_balance(session, context, current, payload)
    outcome = reserve_stock(db, context, actor_id, operation_key, balance_id=balance.id,
        reservation_key=reservation_key, source_line_key=source.stock_source_key(),
        quantity=Decimal(payload.quantity), review_at=payload.review_at, reason=payload.reason,
        input_unit=line.base_unit, authority=claim, authorize=guard, sales_source=source)
    return dict(reservation_key=reservation_key, balance_id=balance.id,
        version=outcome.result['version'], replayed=outcome.replayed)

"""Optional picking preference within an independently authorised store."""
from sqlalchemy import select, or_
from Model.containermgmt.Inventory.Location import InventoryBranch, StockLocation
from Model.containermgmt.Inventory.BranchCounter import BranchCounter, CounterSettingsRevision
from Schema.BranchCounterSchema import CounterConfig
from Services.branch_business_date_service import MissingBranchConfiguration
from Utils.org_filter import apply_org_filter


def require_owned_stock_area(db, context, branch_id, location_id):
    if context.org_id not in context.allowed_org_ids: raise PermissionError('Stock area company denied')
    branch = apply_org_filter(db.query(InventoryBranch).filter_by(id=branch_id,
        org_id=context.org_id, is_active=True, is_deleted=False), InventoryBranch, context).with_for_update(read=True).one_or_none()
    if branch is None: raise LookupError('Choose an active stock area in this branch')
    # Maximum three indexed ancestry probes, never unbounded tree traversal.
    root = None
    expected = None
    for _ in range(3):
        location = apply_org_filter(db.query(StockLocation).filter_by(id=location_id,
            org_id=context.org_id, branch_id=branch_id, is_active=True, is_deleted=False),
            StockLocation, context).populate_existing().with_for_update(read=True).one_or_none()
        if location is None or (expected is not None and location.kind != expected):
            raise LookupError('Stock area ancestry is inactive or invalid')
        if root is None: root = location
        if location.kind == 'SITE' and location.parent_id is None: return root
        expected = {'BIN': 'ZONE', 'ZONE': 'SITE'}.get(location.kind)
        if expected is None or location.parent_id is None: break
        location_id = location.parent_id
    raise LookupError('Stock area ancestry is inactive or invalid')


def counter_stock_area(db, context, *, branch_id, counter_id, expected_version):
    """Current configuration only; caller still authorises and owns transaction."""
    if not db.in_transaction(): raise ValueError('Active transaction required')
    if context.org_id not in context.allowed_org_ids: raise PermissionError('Stock area company denied')
    # Same branch-first order as counter writes, retaining the version until commit.
    branch = apply_org_filter(db.query(InventoryBranch).filter_by(id=branch_id,
        org_id=context.org_id, is_active=True, is_deleted=False), InventoryBranch, context).with_for_update(read=True).one_or_none()
    counter = apply_org_filter(db.query(BranchCounter).filter_by(id=counter_id,
        org_id=context.org_id, branch_id=branch_id, is_deleted=False), BranchCounter, context).one_or_none()
    if branch is None or counter is None: raise LookupError('Counter not found in this active branch')
    revision = apply_org_filter(db.query(CounterSettingsRevision).filter_by(
        counter_id=counter.id, org_id=context.org_id, is_deleted=False),
        CounterSettingsRevision, context).order_by(CounterSettingsRevision.version.desc()).first()
    if revision is None or revision.version != expected_version:
        raise MissingBranchConfiguration('Counter stock area changed; refresh the work context')
    config = CounterConfig.model_validate(revision.config)
    if config.default_stock_location_id is None:
        return None, config
    return require_owned_stock_area(db, context, branch_id, config.default_stock_location_id), config


def stock_area_locations(db, context, root):
    """Advisory root/active-descendant query, bounded to SITE -> ZONE -> BIN.

    Indexed parent probes exclude inactive intermediate zones and other branches.
    No availability, stock lock, staff assignment or posting authority is implied.
    """
    scoped = dict(org_id=context.org_id, branch_id=root.branch_id, is_active=True, is_deleted=False)
    children = select(StockLocation.id).filter_by(**scoped, parent_id=root.id, kind='ZONE')
    included = [StockLocation.id == root.id]
    if root.kind == 'SITE':
        included += [(StockLocation.parent_id == root.id) & (StockLocation.kind == 'ZONE'),
                     StockLocation.parent_id.in_(children) & (StockLocation.kind == 'BIN')]
    elif root.kind == 'ZONE':
        included += [(StockLocation.parent_id == root.id) & (StockLocation.kind == 'BIN')]
    return apply_org_filter(db.query(StockLocation).filter_by(**scoped).filter(or_(*included)), StockLocation, context)


def require_default_stock_area(db, context, action_context):
    """Use only a permission-checked, versioned server branch action context.

    This resolves an optional picking preference, not a stock-access restriction.
    None means no preference within the authorised branch, never another branch.
    Stale/invalid configuration still fails closed.
    """
    from Services.branch_action_context_service import BranchActionContext
    if not isinstance(action_context, BranchActionContext) or not db.in_transaction():
        raise ValueError('Active transaction and trusted branch action context required')
    root, config = counter_stock_area(db, context, branch_id=action_context.branch_id,
        counter_id=action_context.counter_id, expected_version=action_context.counter_settings_version)
    if action_context.action != 'CHECKOUT' or not config.is_enabled or config.purpose not in ('CHECKOUT', 'BOTH'):
        raise PermissionError('Counter is not enabled for sales allocation')
    return root

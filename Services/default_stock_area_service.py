"""Explicit local work-area scope, never a fallback to another store's stock."""
from Model.containermgmt.Inventory.Location import StockLocation
from Model.containermgmt.Inventory.BranchCounter import CounterSettingsRevision
from Schema.BranchCounterSchema import CounterConfig
from Services.branch_business_date_service import MissingBranchConfiguration
from Utils.org_filter import apply_org_filter


def require_owned_stock_area(db, context, branch_id, location_id):
    if context.org_id not in context.allowed_org_ids: raise PermissionError('Stock area company denied')
    location = apply_org_filter(db.query(StockLocation).filter_by(id=location_id,
        org_id=context.org_id, branch_id=branch_id, is_active=True, is_deleted=False), StockLocation, context).with_for_update(read=True).one_or_none()
    if location is None: raise LookupError('Choose an active stock area in this branch')
    return location


def require_default_stock_area(db, context, action_context):
    """Use only a permission-checked, versioned server branch action context.

    This resolves the configured root area, not a stock hold or posting permission.
    Missing/stale defaults never mean the whole branch or another branch.
    """
    from Services.branch_action_context_service import BranchActionContext
    if not isinstance(action_context, BranchActionContext) or not db.in_transaction():
        raise ValueError('Active transaction and trusted branch action context required')
    revision = apply_org_filter(db.query(CounterSettingsRevision).filter_by(
        counter_id=action_context.counter_id, org_id=context.org_id, is_deleted=False),
        CounterSettingsRevision, context).order_by(CounterSettingsRevision.version.desc()).first()
    if revision is None or revision.version != action_context.counter_settings_version:
        raise MissingBranchConfiguration('Counter stock area changed; refresh the work context')
    config = CounterConfig.model_validate(revision.config)
    if not config.is_enabled: raise PermissionError('Counter is disabled')
    if config.default_stock_location_id is None:
        raise MissingBranchConfiguration('Set the counter work area before automatic allocation')
    return require_owned_stock_area(db, context, action_context.branch_id, config.default_stock_location_id)

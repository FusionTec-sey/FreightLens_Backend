"""Settings eligibility only, not permission to post money, stock or collection."""
from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID
from sqlalchemy.orm import Session
from Model.containermgmt.Inventory.Location import InventoryBranch
from Model.containermgmt.Inventory.BranchSettings import BranchSettingsRevision
from Model.containermgmt.Inventory.BranchCounter import BranchCounter, CounterSettingsRevision
from Schema.BranchSettingsSchema import BranchSettingsConfig
from Schema.BranchCounterSchema import CounterConfig
from Services.branch_business_date_service import resolve_business_date, MissingBranchConfiguration
from Utils.org_filter import apply_org_filter


@dataclass(frozen=True)
class BranchActionContext:
    branch_id: int
    counter_id: int
    branch_settings_version: int
    counter_settings_version: int
    business_date: date
    action: str


def require_stock_business_date(db, context, *, branch_id, branch_version, instant, authorize):
    """Reviewed stock allocation uses the target calendar, not a fabricated till.

    The caller separately enforces exact approved scope and runtime ownership.
    Settings remain locked through posting; the version must bind the receipt.
    """
    if not db.in_transaction() or not callable(authorize):
        raise ValueError('Active transaction and stock permission guard required')
    if context.org_id not in context.allowed_org_ids:
        raise PermissionError('Branch action scope denied')
    if type(branch_version) is not int or branch_version <= 0:
        raise MissingBranchConfiguration('Explicit branch settings version required')
    authorize(db)
    branch = apply_org_filter(db.query(InventoryBranch).filter_by(id=branch_id,
        org_id=context.org_id, is_deleted=False, is_active=True), InventoryBranch,
        context).with_for_update(read=True).one_or_none()
    if branch is None: raise LookupError('Active branch not found')
    settings = apply_org_filter(db.query(BranchSettingsRevision).filter_by(
        org_id=context.org_id, branch_id=branch_id, is_deleted=False),
        BranchSettingsRevision, context).order_by(BranchSettingsRevision.version.desc()).first()
    if settings is None: raise MissingBranchConfiguration('Branch trading settings required')
    if settings.version != branch_version:
        raise ValueError('Branch settings changed; reopen the reviewed action')
    calendar = BranchSettingsConfig.model_validate(settings.config)
    resolved = resolve_business_date(instant, calendar.rules(), date_overrides={
        row.business_date: row.is_open for row in calendar.date_overrides})
    if not resolved.trading_allowed:
        raise PermissionError('Stock allocation is closed for this business date')
    return resolved.business_date


def require_branch_action_context(db: Session, context, *, branch_id: int, counter_key: UUID,
                                  branch_version: int, counter_version: int, instant: datetime,
                                  action: str, authorize) -> BranchActionContext:
    """Caller owns transaction. Guard and expected versions apply on every retry.

    Hold a shared branch lock until commit so settings/counter writes cannot race
    posting. Caller must still enforce node authority, money and source eligibility.
    The returned version/date context must be retained on the future transaction.
    """
    if not db.in_transaction():
        raise ValueError("Branch action context requires an active transaction")
    if action not in ("CHECKOUT", "COLLECTION") or not callable(authorize):
        raise ValueError("An explicit supported action and permission guard are required")
    if context.org_id not in context.allowed_org_ids:
        raise PermissionError("Branch action scope denied")
    if any(type(value) is not int or value <= 0 for value in (branch_version, counter_version)):
        raise MissingBranchConfiguration("Explicit positive settings versions are required")
    def scoped(model):
        return apply_org_filter(db.query(model).filter(model.org_id == context.org_id,
            model.is_deleted.is_(False)), model, context)
    branch = scoped(InventoryBranch).filter_by(id=branch_id, is_active=True).with_for_update(read=True).one_or_none()
    if branch is None:
        raise PermissionError("Branch action scope denied")
    authorize(db)
    settings = scoped(BranchSettingsRevision).filter_by(branch_id=branch_id).order_by(BranchSettingsRevision.version.desc()).first()
    counter = scoped(BranchCounter).filter_by(branch_id=branch_id, counter_key=counter_key).one_or_none()
    if settings is None or counter is None:
        raise MissingBranchConfiguration("Branch settings or scoped counter are missing")
    revision = scoped(CounterSettingsRevision).filter_by(counter_id=counter.id).order_by(CounterSettingsRevision.version.desc()).first()
    if revision is None:
        raise MissingBranchConfiguration("Counter settings are missing")
    if settings.version != branch_version or revision.version != counter_version:
        raise ValueError("Branch or counter settings changed; reload before posting")
    config = CounterConfig.model_validate(revision.config)
    if not config.is_enabled or config.purpose not in (action, "BOTH"):
        raise PermissionError("Counter is disabled or not configured for this action")
    calendar = BranchSettingsConfig.model_validate(settings.config)
    resolved = resolve_business_date(instant, calendar.rules(), date_overrides={
        row.business_date: row.is_open for row in calendar.date_overrides})
    if action == "CHECKOUT" and not resolved.trading_allowed:
        raise PermissionError("Checkout is closed for this business date")
    return BranchActionContext(branch_id, counter.id, settings.version, revision.version,
                               resolved.business_date, action)

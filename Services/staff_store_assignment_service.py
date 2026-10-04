"""Staff/store authority is independent of workstation preference and action RBAC."""
from sqlalchemy import or_
from Model.Credentials.users import User
from Model.Credentials.Organisation import Organisation
from Model.containermgmt.Inventory.Location import InventoryBranch
from Model.containermgmt.Inventory.BranchCounter import BranchCounter
from Model.containermgmt.Inventory.StaffStoreAssignment import StaffStoreAssignment
from Schema.StaffStoreAssignmentSchema import StaffStoreConfig
from Services.sales_reservation_source_service import owned
from Services.inventory_posting_service import execute_once, PostingEffect, PostingConflict


def eligible_staff(db, context):
    if context.org_id not in context.allowed_org_ids: raise PermissionError('Company denied')
    # Mirrors effective membership: NULL falls back to home company; [] grants none.
    # Projection deliberately excludes password hashes, contacts and role internals.
    return db.query(User.id, User.username).join(Organisation, Organisation.id == User.org_id).filter(
        User.is_deleted.is_(False), Organisation.is_active.is_(True),
        or_((User.allowed_org_ids.is_(None)) & (User.org_id == context.org_id), User.allowed_org_ids.any(context.org_id)))


def latest_assignment(db, context, user_id):
    return owned(db, StaffStoreAssignment, context).filter_by(user_id=user_id).order_by(StaffStoreAssignment.version.desc()).first()


def require_staff_store_assignment(db, context, user_id, *, branch_id, expected_version):
    if not db.in_transaction(): raise ValueError('Caller transaction required')
    if type(expected_version) is not int or expected_version <= 0: raise ValueError('Assignment version required')
    # Branch-before-user matches configuration writes and the stock authority guard.
    branch = owned(db, InventoryBranch, context).filter_by(id=branch_id, is_active=True).with_for_update(read=True).one_or_none()
    if branch is None: raise PermissionError('Working store unavailable')
    if eligible_staff(db, context).filter(User.id == user_id).with_for_update(read=True, of=User).one_or_none() is None:
        raise PermissionError('Staff company access unavailable')
    current = latest_assignment(db, context, user_id)
    if current is None or not current.is_enabled or current.branch_id != branch_id or current.version != expected_version:
        raise PermissionError('Working-store assignment missing, disabled or changed')
    return current


def save_staff_store_assignment(factory, context, actor_id, operation_key, *, user_id, config, expected_version, authorize):
    if not isinstance(config, StaffStoreConfig): raise ValueError('Typed assignment required')
    if type(user_id) is not int or user_id <= 0 or type(expected_version) is not int or expected_version < 0:
        raise ValueError('Explicit staff identity and expected version required')
    snapshot = StaffStoreConfig.model_validate(config.model_dump()).model_dump(mode='json')
    def guard(db):
        if not callable(authorize): raise ValueError('Assignment administration permission required')
        authorize(db)
        branch = owned(db, InventoryBranch, context).filter_by(id=config.branch_id).with_for_update(read=True).one_or_none()
        if branch is None: raise LookupError('Assigned store not found')
        if config.is_enabled and not branch.is_active: raise PostingConflict('Cannot enable assignment to an inactive branch')
        if eligible_staff(db, context).filter(User.id == user_id).with_for_update(of=User).one_or_none() is None:
            raise LookupError('Staff member not found in this company')
        if config.counter_id is not None and owned(db, BranchCounter, context).filter_by(
                id=config.counter_id, branch_id=config.branch_id).one_or_none() is None:
            raise LookupError('Usual counter not found in assigned store')
    def effect(db):
        previous = latest_assignment(db, context, user_id)
        if (previous.version if previous else 0) != expected_version: raise PostingConflict('Staff assignment changed; refresh before saving')
        db.add(StaffStoreAssignment(org_id=context.org_id, user_id=user_id, version=expected_version+1,
            operation_key=operation_key, created_by=actor_id, **snapshot))
        result = dict(user_id=user_id, version=expected_version+1, config=snapshot)
        return PostingEffect(result, dict(kind='staff.store-assignment', user_id=user_id, version=expected_version+1))
    return execute_once(factory, context, actor_id, operation_key, 'staff.store-assignment.v1',
        dict(user_id=user_id, expected_version=expected_version, config=snapshot), effect, authorize=guard)

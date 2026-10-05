"""Durable in-app delivery for manager cases (T04 remaining scope).

Rows are written inside the caller's case transaction, so a committed request or
decision always has its recipients recorded: there is no separate queue to drift
and no best-effort side channel. Reuses the existing notifications store and its
list/mark-read API rather than adding a second inbox.

Never includes customer names, contacts, amounts or the reason text: a
notification only says which case needs attention, and the case screens enforce
their own permissions when the recipient opens it.
"""
import logging

from sqlalchemy import select

from Model.containermgmt.Orders.Notification import Notification
from Model.Credentials.users import User
from Model.Credentials.roles import Role
from Model.Credentials.user_org_roles import user_org_roles
from Model.Credentials.Organisation import Organisation
from Model.Credentials.role_permissions import role_permissions
from Model.Credentials.permissions import Permission
from auth.policy.catalog import PERMISSION_BY_NAME

# Each case action is reviewed under exactly one permission, so recipients are
# the users holding it. Keep in step with the routers that guard each review.
REVIEW_PERMISSION = {
    # Verified against the permission each review endpoint actually requires;
    # reclassification proposals are reviewed under the policy permission.
    'inventory.policy.activate': 'Review_InventoryPolicy',
    'inventory.stock.reclassify': 'Review_InventoryPolicy',
    'inventory.barcode.retire': 'Review_BarcodeRetirement',
    'inventory.cost.allocate': 'Manage_Financials',
    'inventory.cost.verify-charge': 'Manage_Financials',
    'inventory.reservation.release': 'Review_ReservationRelease',
    'inventory.reservation.reallocate': 'Review_ReservationReallocation',
    'inventory.reservation.review-deadline': 'Review_ReservationDeadline',
    'inventory.reservation.other-area': 'Review_OtherAreaReservation',
    'inventory.count.discrepancy': 'Review_CountDiscrepancy',
}

SUBJECT = {
    'inventory.policy.activate': 'inventory policy',
    'inventory.stock.reclassify': 'stock reclassification',
    'inventory.barcode.retire': 'barcode retirement',
    'inventory.cost.allocate': 'cost allocation',
    'inventory.cost.verify-charge': 'charge evidence',
    'inventory.reservation.release': 'reservation release',
    'inventory.reservation.reallocate': 'reservation reallocation',
    'inventory.reservation.review-deadline': 'reservation follow-up',
    'inventory.reservation.other-area': 'other-area reservation',
    'inventory.count.discrepancy': 'count discrepancy',
}

logger = logging.getLogger(__name__)

REQUESTED = 'CASE_REVIEW_REQUESTED'
DECIDED = 'CASE_REVIEW_DECIDED'
ENTITY = 'MANAGER_CASE'


def subject_of(action):
    return SUBJECT.get(action, 'manager')


def eligible_reviewer_ids(db, org_id, action, *, exclude_user_id=None):
    """Users who may decide this action in this company, excluding the requester.

    Company scope comes from the user's own org plus any explicit allowed company,
    mirroring how the case screens resolve scope. Platform-admin roles are not
    treated as routine recipients; they are not assigned this work.
    """
    permission = REVIEW_PERMISSION.get(action)
    if permission is None:
        # A new case action must be mapped here, or its reviewers are never told.
        # Log loudly rather than failing the case write that already committed.
        logger.warning('No review permission mapped for case action %s; no recipients notified', action)
        return []
    specification = PERMISSION_BY_NAME.get(permission)
    organisation = db.query(Organisation).filter_by(id=org_id, is_active=True).one_or_none()
    modules = set(organisation.modules or []) if organisation is not None else set()
    if specification is None or organisation is None or (
            specification.module and specification.module not in modules) or (
            action == 'inventory.reservation.other-area' and 'INVENTORY' not in modules):
        return []
    allowed = User.allowed_org_ids.isnot(None) & User.allowed_org_ids.any(org_id)
    query = (select(User.id).distinct()
             .join(user_org_roles, (user_org_roles.c.user_id == User.id)
                   & (user_org_roles.c.org_id == org_id))
             .join(Role, Role.id == user_org_roles.c.role_id)
             .join(role_permissions, role_permissions.c.role_id == Role.id)
             .join(Permission, Permission.id == role_permissions.c.permission_id)
             .where(Permission.name == permission,
                    User.is_deleted.is_(False),
                    Role.is_deleted.is_(False),
                    (User.org_id == org_id) | allowed))
    if exclude_user_id is not None:
        query = query.where(User.id != exclude_user_id)
    return [row[0] for row in db.execute(query).all()]


def _add(db, org_id, user_id, event_type, title, message, case_id):
    db.add(Notification(org_id=org_id, user_id=user_id, event_type=event_type,
                        title=title, message=message, link_entity_type=ENTITY,
                        link_entity_id=case_id, is_read=False))


def notify_case_requested(db, context, case, actor_id):
    """Deliver a new request to every other eligible reviewer. Caller owns the transaction."""
    recipients = eligible_reviewer_ids(db, context.org_id, case.action, exclude_user_id=actor_id)
    subject = subject_of(case.action)
    for user_id in recipients:
        _add(db, context.org_id, user_id, REQUESTED,
             f'{subject.capitalize()} review requested',
             f'A {subject} case is waiting for an independent review. '
             'Approval is not execution and cannot be reused for changed details.',
             case.id)
    if recipients:
        db.flush()
    return len(recipients)


def notify_case_decided(db, context, case, outcome, reviewer_id):
    """Tell the requester their case was decided. Caller owns the transaction."""
    if case.created_by is None or case.created_by == reviewer_id:
        return 0
    subject = subject_of(case.action)
    _add(db, context.org_id, case.created_by, DECIDED,
         f'{subject.capitalize()} review {outcome.lower()}',
         f'Your {subject} request was {outcome.lower()} by another authorised reviewer. '
         'Open the case to see the recorded decision and any remaining action.',
         case.id)
    db.flush()
    return 1

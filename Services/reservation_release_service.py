"""Exact saved-demand release bindings for the existing manager-case engine."""
from decimal import Decimal, Context, localcontext
from Model.containermgmt.Inventory.StockLedger import StockBalance, StockReservation, StockMovement
from Model.containermgmt.Inventory.SalesReservationSource import SalesReservationSource
from Model.containermgmt.Inventory.ReservationDeadline import ReservationDeadline
from Model.containermgmt.Inventory.ManagerCase import ManagerCase, ManagerCaseUse
from Model.containermgmt.Orders.SalesIntent import SalesIntent, SalesIntentRevision
from Schema.InventoryPolicySchema import InventoryPolicyConfig
from Services.sales_reservation_source_service import owned
from Services.manager_case_service import CaseBinding
from Services.inventory_posting_service import PostingConflict
from Services.inventory_unit_service import convert_quantity


def locked_reservation_source(db, context, reservation_key):
    if not db.in_transaction(): raise ValueError('Release review requires caller transaction')
    if context.org_id not in context.allowed_org_ids: raise PermissionError('Reservation company denied')
    source = owned(db, SalesReservationSource, context).filter_by(reservation_key=reservation_key).one_or_none()
    if source is None: raise LookupError('Saved-demand reservation not found')
    document = owned(db, SalesIntent, context).filter_by(document_key=source.document_key).with_for_update().one_or_none()
    if document is None: raise LookupError('Saved demand not found')
    revision = owned(db, SalesIntentRevision, context).filter_by(document_key=source.document_key).order_by(SalesIntentRevision.version.desc()).first()
    if revision is None or revision.status != 'DRAFT':
        raise PostingConflict('This release adapter supports unconfirmed draft demand only')
    scope = owned(db, StockReservation, context).filter_by(reservation_key=reservation_key).one_or_none()
    if scope is None: raise LookupError('Reservation not found')
    balance = owned(db, StockBalance, context).filter_by(id=scope.balance_id).with_for_update().populate_existing().one()
    hold = owned(db, StockReservation, context).filter_by(reservation_key=reservation_key).with_for_update().populate_existing().one()
    return source, revision, balance, hold


def current_review_schedule(db, context, hold):
    latest = owned(db, ReservationDeadline, context).filter_by(reservation_key=hold.reservation_key).order_by(ReservationDeadline.version.desc()).first()
    return latest, latest.review_at if latest else hold.review_at, latest.version if latest else 0


def load_release_binding(db, context, reservation_key, quantity, input_unit=None, *,
                         replay_operation=None, case_key=None, expected=None):
    source, revision, balance, hold = locked_reservation_source(db, context, reservation_key)
    base = convert_quantity(InventoryPolicyConfig.model_validate(balance.policy_config), quantity, input_unit or balance.base_unit)
    released = hold.released
    # Only the same case's committed release may normalize its own prior snapshot
    # for receipt replay. Later releases or changed document versions still fail.
    if replay_operation is not None and isinstance(expected, CaseBinding):
        used = owned(db, ManagerCaseUse, context).join(ManagerCase,
            (ManagerCase.id == ManagerCaseUse.case_id) & (ManagerCase.org_id == ManagerCaseUse.org_id)).filter(
                ManagerCase.case_key == case_key, ManagerCaseUse.operation_key == replay_operation).first()
        movement = owned(db, StockMovement, context).filter_by(operation_key=replay_operation,
            reservation_id=hold.id, balance_id=balance.id, kind='RELEASE').one_or_none()
        if used and movement:
            before = Decimal(expected.details['released_before'])
            with localcontext(Context(prec=48)):
                if released == before + base and movement.reserved_delta == -base:
                    released = before
    with localcontext(Context(prec=48)):
        if base > hold.quantity - released: raise PostingConflict('Release exceeds remaining reservation')
    _, review_at, deadline_version = current_review_schedule(db, context, hold)
    return CaseBinding(org_id=context.org_id, action='inventory.reservation.release',
        source_type='sales.reservation', source_key=str(reservation_key), source_version=revision.version,
        details=dict(document_key=str(source.document_key), line_key=str(source.line_key),
            original_source_version=source.version, customer_key=str(revision.customer_key),
            branch_id=revision.branch_id, balance_id=balance.id, product_id=balance.product_id,
            source_line_key=str(hold.source_line_key), base_unit=balance.base_unit,
            held_quantity=format(hold.quantity, 'f'), released_before=format(released, 'f'),
            release_quantity=format(base, 'f'), review_at=review_at.isoformat(), deadline_version=deadline_version, demand_state=revision.status))

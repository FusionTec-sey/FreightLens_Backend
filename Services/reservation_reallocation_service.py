"""Exact same-bucket draft-demand reallocation review, not public stock authority."""
from datetime import datetime, timezone
from decimal import Decimal, Context, localcontext
from uuid import uuid5
from hashlib import sha256
from sqlalchemy import text, select, func
from Model.containermgmt.Inventory.SalesReservationSource import SalesReservationSource
from Model.containermgmt.Inventory.StockLedger import StockReservation, StockMovement
from Model.containermgmt.Inventory.ManagerCase import ManagerCase, ManagerCaseUse
from Model.containermgmt.Inventory.ReservationDeadline import ReservationDeadline
from Model.containermgmt.Orders.SalesIntent import SalesIntent, SalesIntentRevision
from Schema.SalesReservationSchema import SalesDemandReference
from Schema.InventoryPolicySchema import InventoryPolicyConfig
from Services.sales_reservation_source_service import owned, validate_reservation_source
from Services.reservation_release_service import locked_reservation_source, current_review_schedule
from Services.inventory_unit_service import convert_quantity
from Services.inventory_posting_service import PostingConflict
from Services.manager_case_service import CaseBinding


def reallocation_keys(operation):
    return tuple(uuid5(operation, label) for label in ('reallocation-release-v1', 'reallocation-reserve-v1', 'reallocation-target-hold-v1'))


def target_hold_snapshot(db, context, target, balance_id, *, exclude=None):
    """Stream one indexed demand's histories; constant memory, exact review digest.

    Caller owns the target document/allocation lock and stock-bucket lock. Deadline
    and release writers share that document lock, so the snapshot cannot tear.
    """
    latest = select(func.max(ReservationDeadline.version)).where(
        ReservationDeadline.org_id == context.org_id,
        ReservationDeadline.reservation_key == StockReservation.reservation_key).correlate(StockReservation).scalar_subquery()
    query = owned(db, StockReservation, context).outerjoin(SalesReservationSource,
        (SalesReservationSource.org_id == StockReservation.org_id) &
        (SalesReservationSource.reservation_key == StockReservation.reservation_key)).filter(
            StockReservation.source_line_key == target.stock_source_key())
    if exclude is not None: query = query.filter(StockReservation.reservation_key != exclude)
    rows = query.with_entities(StockReservation.reservation_key, StockReservation.balance_id,
        StockReservation.quantity, StockReservation.released, StockReservation.review_at,
        SalesReservationSource.document_key, SalesReservationSource.line_key,
        SalesReservationSource.version, func.coalesce(latest, 0)).order_by(StockReservation.id).yield_per(128)
    digest = sha256(); count = 0; remaining = Decimal(0)
    for key, bucket, held, released, review_at, document, line, version, deadline_version in rows:
        if bucket != balance_id: raise PostingConflict('Another stock bucket requires an explicit multi-location or batch review')
        if document != target.document_key or line != target.line_key:
            raise PostingConflict('Destination reservation history has no matching saved-demand attribution')
        digest.update(f'{key}|{held:f}|{released:f}|{review_at.isoformat()}|{version}|{deadline_version}\n'.encode())
        count += 1
        with localcontext(Context(prec=48)): remaining += held-released
    return dict(count=count, remaining=format(remaining, 'f'), digest=digest.hexdigest())


def require_reallocation_reserve(db, context, actor_id, parent_operation, operation_key,
                                reservation_key, target, balance_id, quantity, review_at):
    """Only the exact consumed parent case may create a supplemental hold segment."""
    release_op, reserve_op, target_key = reallocation_keys(parent_operation)
    if operation_key != reserve_op or reservation_key != target_key or not isinstance(target, SalesDemandReference):
        raise PostingConflict('Reallocation child identity mismatch')
    case = owned(db, ManagerCase, context).join(ManagerCaseUse,
        (ManagerCaseUse.org_id == ManagerCase.org_id) & (ManagerCaseUse.case_id == ManagerCase.id)).filter(
            ManagerCaseUse.operation_key == parent_operation, ManagerCaseUse.created_by == actor_id,
            ManagerCase.action == 'inventory.reservation.reallocate').one_or_none()
    if case is None: raise PermissionError('Consumed reallocation approval required')
    details = case.binding['details']
    release = owned(db, StockMovement, context).filter_by(operation_key=release_op, balance_id=balance_id, kind='RELEASE').one_or_none()
    source = owned(db, StockReservation, context).filter_by(reservation_key=case.source_key).one_or_none()
    if (details['target'] != target.model_dump(mode='json') or details['balance_id'] != balance_id
            or Decimal(details['quantity']) != quantity or datetime.fromisoformat(details['target_review_at']) != review_at
            or release is None or source is None or release.reservation_id != source.id or release.reserved_delta != -quantity):
        raise PostingConflict('Reallocation child differs from approved paired release')
    snapshot = target_hold_snapshot(db, context, target, balance_id, exclude=reservation_key)
    if snapshot != details['target_hold_snapshot']: raise PostingConflict('Destination reservation history changed')
    return snapshot


def load_reallocation_binding(db, context, reservation_key, target, quantity, review_at, *,
                              replay_operation=None, case_key=None, expected=None):
    if not db.in_transaction(): raise ValueError('Active review transaction required')
    if context.org_id not in context.allowed_org_ids: raise PermissionError('Company denied')
    if not isinstance(target, SalesDemandReference): raise ValueError('Typed target sales demand required')
    if not isinstance(review_at, datetime) or review_at.utcoffset() is None: raise ValueError('Explicit aware review date required')
    review_at = review_at.astimezone(timezone.utc)
    source = owned(db, SalesReservationSource, context).filter_by(reservation_key=reservation_key).one_or_none()
    if source is None: raise LookupError('Source demand hold not found')
    # Deterministic document order prevents opposing customer reallocations from
    # holding one document each. Target allocation lock precedes the stock lock.
    documents = sorted({source.document_key, target.document_key})
    locked = owned(db, SalesIntent, context).filter(SalesIntent.document_key.in_(documents)).order_by(SalesIntent.document_key).with_for_update().all()
    if len(locked) != len(documents): raise LookupError('Reallocation demand not found')
    target_source_key = target.stock_source_key()
    db.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))'),
        {'key': f'stock-source:{context.org_id}:{target_source_key}'})
    source, revision, balance, hold = locked_reservation_source(db, context, reservation_key)
    if target_source_key == hold.source_line_key: raise ValueError('Choose a different demand line')
    base = convert_quantity(InventoryPolicyConfig.model_validate(balance.policy_config), quantity, balance.base_unit)
    if base <= 0: raise ValueError('Reallocation quantity must be positive')
    target_line = validate_reservation_source(db, context, target, balance.id, base, balance.base_unit)
    target_revision = owned(db, SalesIntentRevision, context).filter_by(document_key=target.document_key, version=target.version).one()
    if target_revision.status != 'DRAFT': raise PostingConflict('Only unconfirmed draft demand is supported')
    released = hold.released
    own_replay = False
    exclude = None
    if replay_operation is not None and isinstance(expected, CaseBinding):
        release_op, reserve_op, target_key = reallocation_keys(replay_operation)
        use = owned(db, ManagerCaseUse, context).join(ManagerCase,
            (ManagerCase.id == ManagerCaseUse.case_id) & (ManagerCase.org_id == ManagerCaseUse.org_id)).filter(
                ManagerCase.case_key == case_key, ManagerCaseUse.operation_key == replay_operation).first()
        movements = owned(db, StockMovement, context).filter(StockMovement.operation_key.in_([release_op, reserve_op]), StockMovement.balance_id == balance.id).all()
        target_hold = owned(db, StockReservation, context).filter_by(source_line_key=target_source_key, reservation_key=target_key).one_or_none()
        if use and target_hold is not None and len(movements) == 2:
            by_op = {row.operation_key: row for row in movements}
            before = Decimal(expected.details['released_before'])
            with localcontext(Context(prec=48)):
                own_replay = (released == before+base and target_hold.reservation_key == target_key
                    and target_hold.balance_id == balance.id and target_hold.quantity == base and target_hold.released == 0
                    and target_hold.review_at == review_at and by_op[release_op].reservation_id == hold.id
                    and by_op[release_op].reserved_delta == -base and by_op[reserve_op].reservation_id == target_hold.id
                    and by_op[reserve_op].reserved_delta == base)
            if own_replay:
                _, _, target_deadline_version = current_review_schedule(db, context, target_hold)
                if target_deadline_version: raise PostingConflict('Destination follow-up changed after reallocation')
                released = before; exclude = target_key
    target_snapshot = target_hold_snapshot(db, context, target, balance.id, exclude=exclude)
    if not own_replay and review_at <= datetime.now(timezone.utc): raise ValueError('Choose a future target follow-up date')
    with localcontext(Context(prec=48)):
        if base > hold.quantity-released: raise PostingConflict('Reallocation exceeds protected remaining hold')
        if Decimal(target_snapshot['remaining']) + base > target_line.base_quantity:
            raise PostingConflict('Combined destination holds exceed saved line quantity')
    _, source_review_at, deadline_version = current_review_schedule(db, context, hold)
    return CaseBinding(org_id=context.org_id, action='inventory.reservation.reallocate', source_type='sales.reservation',
        source_key=str(reservation_key), source_version=revision.version,
        details=dict(document_key=str(source.document_key), line_key=str(source.line_key), customer_key=str(revision.customer_key),
            branch_id=revision.branch_id, balance_id=balance.id, product_id=balance.product_id, base_unit=balance.base_unit,
            source_line_key=str(hold.source_line_key), held_quantity=format(hold.quantity, 'f'), released_before=format(released, 'f'),
            source_review_at=source_review_at.isoformat(), deadline_version=deadline_version, quantity=format(base, 'f'),
            target=target.model_dump(mode='json'), target_customer_key=str(target_revision.customer_key),
            target_policy_version=target_line.policy_version, target_base_quantity=format(target_line.base_quantity, 'f'),
            target_hold_snapshot=target_snapshot,
            target_review_at=review_at.isoformat()))

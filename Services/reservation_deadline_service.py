"""Reviewed follow-up dates do not change stock or customer financial rights."""
from datetime import datetime, timezone
from Model.containermgmt.Inventory.ReservationDeadline import ReservationDeadline
from Services.reservation_release_service import locked_reservation_source, current_review_schedule
from Services.manager_case_service import CaseBinding, consume_case
from Services.inventory_posting_service import PostingConflict, PostingEffect, execute_once


def load_deadline_binding(db, context, reservation_key, next_review_at, *, replay_operation=None):
    if not isinstance(next_review_at, datetime) or next_review_at.tzinfo is None or next_review_at.utcoffset() is None:
        raise ValueError('An explicit timezone-aware next review date is required')
    next_review_at = next_review_at.astimezone(timezone.utc)
    source, revision, balance, hold = locked_reservation_source(db, context, reservation_key)
    if hold.quantity <= hold.released: raise PostingConflict('No remaining stock is held for follow-up')
    latest, current, version = current_review_schedule(db, context, hold)
    # Immutable own-operation history is the only permitted replay normalization.
    if latest is not None and latest.operation_key == replay_operation:
        current, version = latest.previous_review_at, latest.version-1
    elif next_review_at <= datetime.now(timezone.utc):
        raise ValueError('Choose a future follow-up date')
    if next_review_at <= current: raise ValueError('Next review must be later than the current review date')
    return CaseBinding(org_id=context.org_id, action='inventory.reservation.review-deadline',
        source_type='sales.reservation', source_key=str(reservation_key), source_version=revision.version,
        details=dict(document_key=str(source.document_key), line_key=str(source.line_key),
            customer_key=str(revision.customer_key), branch_id=revision.branch_id, balance_id=balance.id,
            product_id=balance.product_id, base_unit=balance.base_unit,
            held_quantity=format(hold.quantity, 'f'), released_before=format(hold.released, 'f'),
            deadline_version=version, review_at=current.astimezone(timezone.utc).isoformat(),
            next_review_at=next_review_at.isoformat(), demand_state=revision.status))


def apply_reviewed_deadline(factory, context, actor_id, operation_key, *, case_key, binding, authorize):
    if not isinstance(binding, CaseBinding) or binding.action != 'inventory.reservation.review-deadline':
        raise ValueError('An exact reservation deadline case is required')
    from uuid import UUID
    key = UUID(binding.source_key); next_date = datetime.fromisoformat(binding.details['next_review_at'])
    def load(db): return load_deadline_binding(db, context, key, next_date, replay_operation=operation_key)
    def guard(db):
        if not callable(authorize): raise ValueError('Explicit deadline permission guard required')
        authorize(db)
        if load(db).snapshot() != binding.snapshot(): raise PostingConflict('Reservation follow-up source changed')
    def apply(db):
        consume_case(db, context, actor_id, operation_key, case_key=case_key, binding=binding,
            load_binding=load, authorize=authorize)
        version = binding.details['deadline_version']+1
        db.add(ReservationDeadline(org_id=context.org_id, reservation_key=key, case_key=case_key,
            operation_key=operation_key, version=version,
            previous_review_at=datetime.fromisoformat(binding.details['review_at']), review_at=next_date, created_by=actor_id))
        db.flush()
        return PostingEffect(dict(reservation_key=str(key), deadline_version=version, review_at=next_date.isoformat()),
            dict(kind='inventory.reservation.follow-up-scheduled', reservation_key=str(key), deadline_version=version))
    return execute_once(factory, context, actor_id, operation_key, 'inventory.reservation.deadline.v1',
        dict(case_key=str(case_key), binding=binding.snapshot()), apply, authorize=guard)

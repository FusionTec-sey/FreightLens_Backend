"""Independent review of a provisional count difference (T33A).

Reuses the existing manager-case engine, so self-review, reuse of an approval
against changed details and double decisions are already refused. A decision
records a judgement about the count: it authorises no stock adjustment, no
valuation and no freeze. Movement-aware reconciliation remains T09/T33.
"""
from decimal import Decimal
from uuid import UUID

from Model.containermgmt.Inventory.CycleCount import (CountDiscrepancy, CountDiscrepancyReview,
                                                      CountSession)
from Services.inventory_posting_service import PostingConflict
from Services.manager_case_service import CaseBinding, request_case, review_case
from Services.count_plan_service import owned

ACTION = 'inventory.count.discrepancy'
SOURCE_TYPE = 'inventory.count.discrepancy'


def locked_discrepancy(db, context, discrepancy_id, *, for_update=True):
    if not db.in_transaction():
        raise ValueError('Discrepancy review requires a caller transaction')
    if context.org_id not in context.allowed_org_ids:
        raise PermissionError('Count discrepancy company scope denied')
    query = owned(db, CountDiscrepancy, context).filter_by(id=discrepancy_id)
    row = (query.with_for_update() if for_update else query).one_or_none()
    if row is None:
        raise LookupError('Count discrepancy not found')
    session = owned(db, CountSession, context).filter_by(id=row.session_id).one()
    return row, session


def load_discrepancy_binding(db, context, discrepancy_id):
    """Bind the exact counted and expected figures the reviewer is deciding on.

    The counted figure is immutable, so a review can never silently apply to a
    different count. The expected figure is the submission-time snapshot and is
    carried as provisional information only.
    """
    row, session = locked_discrepancy(db, context, discrepancy_id)
    return CaseBinding(org_id=context.org_id, action=ACTION, source_type=SOURCE_TYPE,
                       source_key=str(row.id), source_version=session.round,
                       details=dict(discrepancy_id=row.id, session_key=str(session.session_key),
                                    round=session.round, product_id=row.product_id,
                                    location_id=row.location_id, base_unit=row.base_unit,
                                    counted_base=format(row.counted_base, 'f'),
                                    expected_base=format(row.expected_base, 'f'),
                                    difference_base=format(row.difference_base, 'f'),
                                    expected_snapshot_version=row.balance_version))


def request_discrepancy_review(db, context, actor_id, operation_key, discrepancy_id, payload, *, authorize):
    authorize(db)
    row, _ = locked_discrepancy(db, context, discrepancy_id)
    if owned(db, CountDiscrepancyReview, context).filter_by(discrepancy_id=row.id).first():
        raise PostingConflict('This discrepancy has already been reviewed')
    load = lambda session: load_discrepancy_binding(session, context, discrepancy_id)
    binding = load(db)
    if Decimal(binding.details['counted_base']) != Decimal(payload.expected_counted_base):
        raise PostingConflict('Counted figure changed; refresh before requesting a review')
    return request_case(db, context, actor_id, operation_key, binding=binding,
                        reason=payload.reason, load_binding=load, authorize=authorize)


def decide_discrepancy(db, context, actor_id, operation_key, discrepancy_id, payload, *, authorize):
    """Record the decision and append the immutable review row in one transaction."""
    authorize(db)
    load = lambda session: load_discrepancy_binding(session, context, discrepancy_id)
    row, session = locked_discrepancy(db, context, discrepancy_id)
    previous = owned(db, CountDiscrepancyReview, context).filter_by(discrepancy_id=row.id).one_or_none()
    if previous is not None and (previous.case_key != payload.case_key or
            previous.outcome != payload.outcome or previous.reason != payload.reason or
            previous.created_by != actor_id):
        raise PostingConflict('This discrepancy has already been reviewed with different details')
    # Manager cases carry APPROVED or REJECTED; the count outcome is the business
    # meaning stored beside it, so RECOUNT_REQUIRED is an approved decision that
    # asks for another round rather than accepting the figure.
    outcome = 'REJECTED' if payload.outcome == 'REJECTED' else 'APPROVED'
    result = review_case(db, context, actor_id, operation_key, case_key=payload.case_key,
                         binding=load(db), expected_version=payload.expected_version,
                         outcome=outcome, reason=payload.reason, load_binding=load,
                         authorize=authorize)
    if result.replayed:
        if previous is None:
            raise PostingConflict('Count decision receipt is missing its immutable review')
        return result
    db.add(CountDiscrepancyReview(org_id=context.org_id, discrepancy_id=row.id,
                                  case_key=payload.case_key, outcome=payload.outcome,
                                  reason=payload.reason, created_by=actor_id))
    db.flush()
    return result


def review_state(db, context, discrepancy_ids):
    """Reviewed state is derived from the append-only review rows, never stored."""
    if not discrepancy_ids:
        return {}
    rows = owned(db, CountDiscrepancyReview, context).filter(
        CountDiscrepancyReview.discrepancy_id.in_(discrepancy_ids)).all()
    return {row.discrepancy_id: row for row in rows}

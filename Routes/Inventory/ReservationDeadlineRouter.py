"""Reviewed follow-up scheduling; no stock release or financial effect."""
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from Model.db import get_db
from Model.containermgmt.Inventory.ManagerCase import ManagerCase
from Schema.ReservationDeadlineSchema import DeadlineRequest, DeadlineCaseRead, DeadlineApply, DeadlineApplied
from Schema.ManagerCaseSchema import PolicyCaseReview, CaseActionRead
from Schema.InventoryLocationSchema import LocationPage
from Schema.ReservationReleaseCaseSchema import ReservationSourceRead
from Services.reservation_source_read_service import reservation_sources_page
from Services.reservation_deadline_service import load_deadline_binding, apply_reviewed_deadline
from Services.manager_case_service import CaseBinding, request_case, review_case
from Services.manager_case_read_service import case_page, case_metadata
from Services.inventory_posting_service import PostingConflict
from Services.sales_reservation_source_service import owned
from Routes.Inventory.ReservationReleaseCaseRouter import translate, guard
from Routes.Orders.SalesIntentRouter import draft_access
from Routes.MasterData.CustomerRouter import private_response
from auth.module_guard import require_module
from auth.policy import AccessPolicy
from auth.security_guards import require_permission
from auth.dependencies import get_org_context, get_current_user
from Utils.org_filter import OrgContext

ReservationDeadlineRouter = APIRouter(prefix='/inventory/reservation-deadline-cases', tags=['Reservation follow-up'],
    dependencies=[Depends(require_module('INVENTORY')), Depends(require_module('SALES')), Depends(draft_access), Depends(private_response)])
ACTION = 'inventory.reservation.review-deadline'


@ReservationDeadlineRouter.get('/due', response_model=LocationPage[ReservationSourceRead])
def due_followups(page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
                  branch_id: int | None = Query(None, gt=0), db: Session = Depends(get_db),
                  context: OrgContext = Depends(get_org_context), policy: AccessPolicy = Depends(draft_access)):
    if not policy.has('Review_ReservationDeadline') and not policy.has('Schedule_ReservationReview'):
        raise HTTPException(403, 'Manager follow-up access required')
    try: return reservation_sources_page(db, context, page=page, limit=limit, due_only=True, branch_id=branch_id)
    except (LookupError, PermissionError, ValueError) as error: raise translate(error) from error


def load_case(db, context, key):
    case = owned(db, ManagerCase, context).filter_by(case_key=key, action=ACTION, source_type='sales.reservation').one_or_none()
    if case is None: raise LookupError('Reservation deadline case not found')
    return case, CaseBinding(**case.binding)


@ReservationDeadlineRouter.post('', response_model=CaseActionRead)
def request_deadline(payload: DeadlineRequest, db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
                     policy: AccessPolicy = Depends(draft_access), user=Depends(require_permission('Request_ReservationDeadline'))):
    try:
        if not db.in_transaction(): db.begin()
        load = lambda session: load_deadline_binding(session, context, payload.reservation_key, payload.next_review_at)
        binding = load(db)
        if (binding.source_version != payload.expected_source_version or binding.details['deadline_version'] != payload.expected_deadline_version
            or Decimal(binding.details['released_before']) != Decimal(payload.expected_released)):
            raise PostingConflict('Reservation changed; refresh before requesting a follow-up date')
        result = request_case(db, context, user.id, payload.operation_key, binding=binding, reason=payload.reason,
            load_binding=load, authorize=guard(policy, 'Request_ReservationDeadline'))
        db.commit(); return dict(**result.result, replayed=result.replayed)
    except Exception as error:
        db.rollback(); raise translate(error) from error


@ReservationDeadlineRouter.get('', response_model=LocationPage[DeadlineCaseRead])
def list_deadline_cases(page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
                        view: Literal['ALL', 'MY_REQUESTS', 'NEEDS_MY_REVIEW'] = 'ALL',
                        db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
                        policy: AccessPolicy = Depends(draft_access), user=Depends(get_current_user)):
    if context.org_id not in context.allowed_org_ids: raise HTTPException(403, 'Company denied')
    can_review = policy.has('Review_ReservationDeadline')
    if not can_review and not policy.has('Request_ReservationDeadline') and not policy.has('Schedule_ReservationReview'):
        raise HTTPException(403, 'Reservation follow-up access required')
    query = owned(db, ManagerCase, context).filter_by(action=ACTION, source_type='sales.reservation')
    if not can_review and not policy.has('Schedule_ReservationReview'): query = query.filter(ManagerCase.created_by == user.id)
    total, rows = case_page(db, query, user.id, view, page, limit)
    fields = ('document_key', 'line_key', 'base_unit', 'held_quantity', 'released_before', 'deadline_version', 'review_at', 'next_review_at')
    return dict(items=[dict(**case_metadata(case, decision, used), reservation_key=case.source_key,
        **{name: case.binding['details'][name] for name in fields}) for case, decision, used in rows],
        total=total, page=page, limit=limit, pages=max(1, (total+limit-1)//limit))


@ReservationDeadlineRouter.post('/{key}/review', response_model=CaseActionRead)
def review_deadline(key: UUID, payload: PolicyCaseReview, db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
                    policy: AccessPolicy = Depends(draft_access), user=Depends(require_permission('Review_ReservationDeadline'))):
    try:
        case, binding = load_case(db, context, key)
        result = review_case(db, context, user.id, payload.operation_key, case_key=key, binding=binding,
            expected_version=payload.expected_version, outcome=payload.outcome, reason=payload.reason,
            load_binding=lambda session: load_deadline_binding(session, context, UUID(case.source_key), datetime.fromisoformat(binding.details['next_review_at'])),
            authorize=guard(policy, 'Review_ReservationDeadline'))
        db.commit(); return dict(**result.result, replayed=result.replayed)
    except Exception as error:
        db.rollback(); raise translate(error) from error


@ReservationDeadlineRouter.post('/{key}/schedule', response_model=DeadlineApplied)
def schedule_deadline(key: UUID, payload: DeadlineApply, db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
                      policy: AccessPolicy = Depends(draft_access), user=Depends(require_permission('Schedule_ReservationReview'))):
    try:
        _, binding = load_case(db, context, key)
        result = apply_reviewed_deadline(db, context, user.id, payload.operation_key, case_key=key,
            binding=binding, authorize=guard(policy, 'Schedule_ReservationReview'))
        db.commit(); return dict(**result.result, replayed=result.replayed)
    except Exception as error:
        db.rollback(); raise translate(error) from error

"""Request/review only: approval is not an HTTP stock-writing entitlement."""
from decimal import Decimal
from uuid import UUID
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from Model.db import get_db
from Model.containermgmt.Inventory.ManagerCase import ManagerCase
from Schema.ReservationReleaseCaseSchema import ReleaseCaseRequest, ReleaseCaseRead, ReservationSourceRead
from Services.reservation_source_read_service import reservation_sources_page
from Schema.ManagerCaseSchema import PolicyCaseReview, CaseActionRead
from Schema.InventoryLocationSchema import LocationPage
from Services.reservation_release_service import load_release_binding
from Services.manager_case_service import CaseBinding, request_case, review_case
from Services.manager_case_read_service import case_page, case_metadata
from Services.inventory_posting_service import PostingConflict
from Services.sales_reservation_source_service import owned
from Routes.Orders.SalesIntentRouter import draft_access
from Routes.MasterData.CustomerRouter import private_response
from auth.module_guard import require_module
from auth.policy import AccessPolicy
from auth.security_guards import require_permission
from auth.dependencies import get_org_context, get_current_user
from Utils.org_filter import OrgContext

ReservationReleaseCaseRouter = APIRouter(prefix='/inventory/reservation-release-cases', tags=['Reservation reviews'],
    dependencies=[Depends(require_module('INVENTORY')), Depends(require_module('SALES')),
                  Depends(draft_access), Depends(private_response)])


def translate(error):
    if isinstance(error, LookupError): return HTTPException(404, 'Reservation source not found')
    if isinstance(error, PermissionError): return HTTPException(403, str(error))
    if isinstance(error, PostingConflict): return HTTPException(409, str(error))
    if isinstance(error, ValueError): return HTTPException(422, str(error))
    return error


def guard(policy, permission):
    def check(db):
        draft_access(policy)
        if not policy.has(permission): raise PermissionError('Reservation review permission required')
    return check


@ReservationReleaseCaseRouter.get('/sources/{key}', response_model=LocationPage[ReservationSourceRead])
def list_sources(key: UUID, page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
                 db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
                 policy: AccessPolicy = Depends(draft_access)):
    if context.org_id not in context.allowed_org_ids: raise HTTPException(403, 'Company denied')
    if not any(policy.has(p) for p in ('Request_ReservationRelease', 'Review_ReservationRelease',
                                      'Request_ReservationReallocation', 'Review_ReservationReallocation',
                                      'Request_ReservationDeadline', 'Review_ReservationDeadline', 'Schedule_ReservationReview')):
        raise HTTPException(403, 'Reservation review access required')
    try: return reservation_sources_page(db, context, page=page, limit=limit, document_key=key)
    except (LookupError, PermissionError, ValueError) as error: raise translate(error) from error


@ReservationReleaseCaseRouter.post('', response_model=CaseActionRead)
def request_release(payload: ReleaseCaseRequest, db: Session = Depends(get_db),
                    context: OrgContext = Depends(get_org_context), policy: AccessPolicy = Depends(draft_access),
                    user=Depends(require_permission('Request_ReservationRelease'))):
    try:
        if not db.in_transaction(): db.begin()
        binding = load_release_binding(db, context, payload.reservation_key, Decimal(payload.quantity))
        if binding.source_version != payload.expected_source_version or Decimal(binding.details['released_before']) != Decimal(payload.expected_released):
            raise PostingConflict('Reservation or demand changed; refresh before requesting review')
        result = request_case(db, context, user.id, payload.operation_key, binding=binding, reason=payload.reason,
            load_binding=lambda session: load_release_binding(session, context, payload.reservation_key, Decimal(payload.quantity)),
            authorize=guard(policy, 'Request_ReservationRelease'))
        db.commit()
        return dict(**result.result, replayed=result.replayed)
    except Exception as error:
        db.rollback(); raise translate(error) from error


@ReservationReleaseCaseRouter.get('', response_model=LocationPage[ReleaseCaseRead])
def list_release_cases(page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
                       view: Literal['ALL', 'MY_REQUESTS', 'NEEDS_MY_REVIEW'] = 'ALL',
                       db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
                       policy: AccessPolicy = Depends(draft_access), user=Depends(get_current_user)):
    if context.org_id not in context.allowed_org_ids: raise HTTPException(403, 'Company denied')
    can_review = policy.has('Review_ReservationRelease')
    if not can_review and not policy.has('Request_ReservationRelease'): raise HTTPException(403, 'Reservation review access required')
    query = owned(db, ManagerCase, context).filter_by(action='inventory.reservation.release', source_type='sales.reservation')
    if not can_review: query = query.filter(ManagerCase.created_by == user.id)
    total, rows = case_page(db, query, user.id, view, page, limit)
    items = [dict(**case_metadata(case, decision, used), reservation_key=case.source_key,
        **{key: case.binding['details'][key] for key in ('document_key', 'line_key', 'release_quantity', 'base_unit', 'held_quantity', 'released_before')})
        for case, decision, used in rows]
    return dict(items=items, total=total, page=page, limit=limit, pages=max(1, (total+limit-1)//limit))


@ReservationReleaseCaseRouter.post('/{key}/review', response_model=CaseActionRead)
def review_release(key: UUID, payload: PolicyCaseReview, db: Session = Depends(get_db),
                   context: OrgContext = Depends(get_org_context), policy: AccessPolicy = Depends(draft_access),
                   user=Depends(require_permission('Review_ReservationRelease'))):
    try:
        case = owned(db, ManagerCase, context).filter_by(case_key=key,
            action='inventory.reservation.release', source_type='sales.reservation').one_or_none()
        if case is None: raise LookupError('Case not found')
        binding = CaseBinding(**case.binding)
        result = review_case(db, context, user.id, payload.operation_key, case_key=key, binding=binding,
            expected_version=payload.expected_version, outcome=payload.outcome, reason=payload.reason,
            load_binding=lambda session: load_release_binding(session, context, UUID(case.source_key),
                Decimal(binding.details['release_quantity']), binding.details['base_unit']),
            authorize=guard(policy, 'Review_ReservationRelease'))
        db.commit()
        return dict(**result.result, replayed=result.replayed)
    except Exception as error:
        db.rollback(); raise translate(error) from error

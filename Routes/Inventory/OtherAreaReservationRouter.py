"""Sales draft requests for stock outside the selected counter work area."""
from decimal import Decimal
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from Model.db import get_db
from Model.containermgmt.Inventory.ManagerCase import ManagerCase
from Model.containermgmt.Inventory.StockLedger import StockBalance
from Model.containermgmt.Orders.SalesIntent import SalesIntentLineRevision
from Schema.SalesAreaPreviewSchema import OtherAreaRequest, OtherAreaBalance, OtherAreaReserveReceipt
from Schema.InventoryLocationSchema import LocationPage
from Schema.ManagerCaseSchema import PolicyCaseReview, CaseActionRead
from Services.inventory_posting_service import PostingConflict
from Services.manager_case_service import CaseBinding, request_case, review_case
from Services.manager_case_read_service import case_page, case_metadata
from Services.sales_other_area_service import ACTION, outside_balances, load_binding, reload_binding, execute_approved
from Services.sales_reservation_source_service import owned, active_demand_holds
from Routes.Orders.SalesIntentRouter import draft_access
from Routes.MasterData.CustomerRouter import private_response
from auth.module_guard import require_module
from auth.policy import AccessPolicy
from auth.security_guards import require_permission
from auth.dependencies import get_org_context, get_current_user
from Utils.org_filter import OrgContext


OtherAreaReservationRouter = APIRouter(prefix='/inventory/other-area-reservations', tags=['Sales stock exceptions'],
    dependencies=[Depends(require_module('SALES')), Depends(require_module('INVENTORY')),
                  Depends(draft_access), Depends(private_response)])


def translate(error):
    if isinstance(error, LookupError): return HTTPException(404, str(error))
    if isinstance(error, PermissionError): return HTTPException(403, str(error))
    if isinstance(error, PostingConflict): return HTTPException(409, str(error))
    if isinstance(error, ValueError): return HTTPException(422, str(error))
    return error


def guard(policy, permission):
    def check(db):
        draft_access(policy)
        if not policy.has(permission): raise PermissionError('Other-area reservation permission required')
    return check


@OtherAreaReservationRouter.get('/candidates', response_model=LocationPage[OtherAreaBalance])
def candidates(document_key: UUID, expected_draft_version: int = Query(..., gt=0),
               line_key: UUID = Query(...), counter_key: UUID = Query(...),
               counter_version: int = Query(..., gt=0), page: int = Query(1, ge=1),
               limit: int = Query(25, ge=1, le=100), db: Session = Depends(get_db),
               context: OrgContext = Depends(get_org_context),
               user=Depends(require_permission('Request_OtherAreaReservation'))):
    try:
        if context.org_id not in context.allowed_org_ids: raise PermissionError('Company denied')
        return outside_balances(db, context, document_key, expected_draft_version, line_key,
            counter_key, counter_version, page, limit)
    except Exception as error: raise translate(error) from error


@OtherAreaReservationRouter.post('', response_model=CaseActionRead)
def request_other_area(payload: OtherAreaRequest, db: Session = Depends(get_db),
                       context: OrgContext = Depends(get_org_context),
                       policy: AccessPolicy = Depends(draft_access),
                       user=Depends(require_permission('Request_OtherAreaReservation'))):
    try:
        if context.org_id not in context.allowed_org_ids: raise PermissionError('Company denied')
        if not db.in_transaction(): db.begin()
        binding = load_binding(db, context, document_key=payload.document_key,
            version=payload.expected_draft_version, line_key=payload.line_key,
            counter_key=payload.counter_key, counter_version=payload.counter_version,
            balance_id=payload.balance_id, quantity=payload.quantity, review_at=payload.review_at)
        held = active_demand_holds(db, context, payload.document_key).get(payload.line_key, Decimal(0))
        line_quantity = owned(db, SalesIntentLineRevision, context).filter_by(
            document_key=payload.document_key, version=payload.expected_draft_version,
            line_key=payload.line_key).one().base_quantity
        if held + Decimal(payload.quantity) > line_quantity:
            raise PostingConflict('Requested hold exceeds remaining saved demand')
        balance = owned(db, StockBalance, context).filter_by(id=payload.balance_id).one()
        # Availability is rechecked by the stock writer when approval is executed.
        if Decimal(payload.quantity) > balance.on_hand - balance.reserved - balance.damaged - balance.quarantined:
            raise PostingConflict('Selected stock is no longer available; refresh choices')
        result = request_case(db, context, user.id, payload.operation_key, binding=binding,
            reason=payload.reason, load_binding=lambda session: reload_binding(session, context, binding),
            authorize=guard(policy, 'Request_OtherAreaReservation'))
        db.commit()
        return dict(**result.result, replayed=result.replayed)
    except Exception as error:
        db.rollback(); raise translate(error) from error


@OtherAreaReservationRouter.get('', response_model=LocationPage[dict])
def list_cases(page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
               view: Literal['ALL', 'MY_REQUESTS', 'NEEDS_MY_REVIEW'] = 'ALL',
               db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
               policy: AccessPolicy = Depends(draft_access), user=Depends(get_current_user)):
    if context.org_id not in context.allowed_org_ids: raise HTTPException(403, 'Company denied')
    can_review = policy.has('Review_OtherAreaReservation')
    can_execute = policy.has('Execute_OtherAreaReservation')
    if not (can_review or can_execute or policy.has('Request_OtherAreaReservation')):
        raise HTTPException(403, 'Other-area reservation access required')
    query = owned(db, ManagerCase, context).filter_by(action=ACTION, source_type='sales.demand')
    if not can_review and not can_execute: query = query.filter(ManagerCase.created_by == user.id)
    total, rows = case_page(db, query, user.id, view, page, limit)
    items = [dict(**case_metadata(case, decision, used), **case.binding['details'])
        for case, decision, used in rows]
    return dict(items=items, total=total, page=page, limit=limit,
        pages=max(1, (total + limit - 1) // limit))


@OtherAreaReservationRouter.post('/{key}/review', response_model=CaseActionRead)
def review_other_area(key: UUID, payload: PolicyCaseReview, db: Session = Depends(get_db),
                      context: OrgContext = Depends(get_org_context),
                      policy: AccessPolicy = Depends(draft_access),
                      user=Depends(require_permission('Review_OtherAreaReservation'))):
    try:
        case = owned(db, ManagerCase, context).filter_by(case_key=key,
            action=ACTION, source_type='sales.demand').one_or_none()
        if case is None: raise LookupError('Case not found')
        binding = CaseBinding(**case.binding)
        result = review_case(db, context, user.id, payload.operation_key, case_key=key,
            binding=binding, expected_version=payload.expected_version,
            outcome=payload.outcome, reason=payload.reason,
            load_binding=lambda session: reload_binding(session, context, binding),
            authorize=guard(policy, 'Review_OtherAreaReservation'))
        db.commit()
        return dict(**result.result, replayed=result.replayed)
    except Exception as error:
        db.rollback(); raise translate(error) from error


@OtherAreaReservationRouter.post('/{key}/reserve', response_model=OtherAreaReserveReceipt)
def reserve_approved(key: UUID, db: Session = Depends(get_db),
                     context: OrgContext = Depends(get_org_context),
                     policy: AccessPolicy = Depends(draft_access),
                     user=Depends(require_permission('Execute_OtherAreaReservation'))):
    try:
        case = owned(db, ManagerCase, context).filter_by(case_key=key,
            action=ACTION, source_type='sales.demand').one_or_none()
        if case is None: raise LookupError('Case not found')
        result = execute_approved(db, context, user.id, case, CaseBinding(**case.binding),
            authorize=guard(policy, 'Execute_OtherAreaReservation'))
        db.commit()
        return result
    except Exception as error:
        db.rollback(); raise translate(error) from error

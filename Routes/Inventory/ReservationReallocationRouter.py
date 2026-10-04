"""Scoped reallocation requests/decisions; no client-supplied stock authority."""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from Model.db import get_db
from Model.containermgmt.Inventory.ManagerCase import ManagerCase
from Schema.ReservationReallocationSchema import ReallocationCaseRequest, ReallocationCaseRead
from Schema.ReservationReallocationSchema import ReallocationExecutionRequest, ReallocationExecutionContext, ReallocationExecutionRead
from Services.reviewed_stock_runtime_service import reviewed_stock_scope
from Services.stock_runtime_service import StockRuntimeUnavailable
from Services.stock_ledger_service import reallocate_reservation
from Services.branch_action_context_service import require_stock_business_date
from Routes.Inventory.BranchSettingsRouter import read_settings
from Schema.SalesReservationSchema import SalesDemandReference
from Schema.ManagerCaseSchema import PolicyCaseReview, CaseActionRead
from Schema.InventoryLocationSchema import LocationPage
from Services.reservation_reallocation_service import load_reallocation_binding
from Services.manager_case_service import CaseBinding, request_case, review_case
from Services.manager_case_read_service import case_page, case_metadata
from Services.inventory_posting_service import PostingConflict
from Services.sales_reservation_source_service import owned
from Routes.Inventory.ReservationReleaseCaseRouter import guard, translate
from Routes.Orders.SalesIntentRouter import draft_access
from Routes.MasterData.CustomerRouter import private_response
from auth.module_guard import require_module
from auth.policy import AccessPolicy
from auth.security_guards import require_permission
from auth.dependencies import get_org_context, get_current_user
from Utils.org_filter import OrgContext

ReservationReallocationRouter = APIRouter(prefix='/inventory/reservation-reallocation-cases', tags=['Reservation reviews'],
    dependencies=[Depends(require_module('INVENTORY')), Depends(require_module('SALES')),
                  Depends(draft_access), Depends(private_response)])


@ReservationReallocationRouter.post('', response_model=CaseActionRead)
def request_reallocation(payload: ReallocationCaseRequest, db: Session = Depends(get_db),
                         context: OrgContext = Depends(get_org_context), policy: AccessPolicy = Depends(draft_access),
                         user=Depends(require_permission('Request_ReservationReallocation'))):
    try:
        if not db.in_transaction(): db.begin()
        def load(session):
            return load_reallocation_binding(session, context, payload.reservation_key, payload.target,
                Decimal(payload.quantity), payload.review_at)
        binding = load(db)
        if binding.source_version != payload.expected_source_version or Decimal(binding.details['released_before']) != Decimal(payload.expected_released):
            raise PostingConflict('Reservation or demand changed; refresh before requesting review')
        result = request_case(db, context, user.id, payload.operation_key, binding=binding, reason=payload.reason,
            load_binding=load, authorize=guard(policy, 'Request_ReservationReallocation'))
        db.commit()
        return dict(**result.result, replayed=result.replayed)
    except Exception as error:
        db.rollback(); raise translate(error) from error


@ReservationReallocationRouter.get('', response_model=LocationPage[ReallocationCaseRead])
def list_reallocations(page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
                       view: Literal['ALL', 'MY_REQUESTS', 'NEEDS_MY_REVIEW'] = 'ALL',
                       db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
                       policy: AccessPolicy = Depends(draft_access), user=Depends(get_current_user)):
    if context.org_id not in context.allowed_org_ids: raise HTTPException(403, 'Company denied')
    can_review = policy.has('Review_ReservationReallocation')
    can_execute = policy.has('Execute_ReservationReallocation')
    if not can_review and not can_execute and not policy.has('Request_ReservationReallocation'):
        raise HTTPException(403, 'Reservation review access required')
    query = owned(db, ManagerCase, context).filter_by(action='inventory.reservation.reallocate', source_type='sales.reservation')
    if not can_review and not can_execute: query = query.filter(ManagerCase.created_by == user.id)
    total, rows = case_page(db, query, user.id, view, page, limit)
    fields = ('document_key', 'line_key', 'quantity', 'base_unit', 'held_quantity', 'released_before', 'target', 'target_review_at')
    items = [dict(**case_metadata(case, decision, used), reservation_key=case.source_key,
        target_hold_snapshot=case.binding['details'].get('target_hold_snapshot'),
        **{key: case.binding['details'][key] for key in fields}) for case, decision, used in rows]
    return dict(items=items, total=total, page=page, limit=limit, pages=max(1, (total+limit-1)//limit))


@ReservationReallocationRouter.post('/{key}/review', response_model=CaseActionRead)
def review_reallocation(key: UUID, payload: PolicyCaseReview, db: Session = Depends(get_db),
                        context: OrgContext = Depends(get_org_context), policy: AccessPolicy = Depends(draft_access),
                        user=Depends(require_permission('Review_ReservationReallocation'))):
    try:
        case = owned(db, ManagerCase, context).filter_by(case_key=key,
            action='inventory.reservation.reallocate', source_type='sales.reservation').one_or_none()
        if case is None: raise LookupError('Case not found')
        binding = CaseBinding(**case.binding); details = binding.details
        result = review_case(db, context, user.id, payload.operation_key, case_key=key, binding=binding,
            expected_version=payload.expected_version, outcome=payload.outcome, reason=payload.reason,
            load_binding=lambda session: load_reallocation_binding(session, context, UUID(case.source_key),
                SalesDemandReference.model_validate(details['target']), Decimal(details['quantity']),
                datetime.fromisoformat(details['target_review_at'])),
            authorize=guard(policy, 'Review_ReservationReallocation'))
        db.commit()
        return dict(**result.result, replayed=result.replayed)
    except Exception as error:
        db.rollback(); raise translate(error) from error


@ReservationReallocationRouter.get('/{key}/execution-context', response_model=ReallocationExecutionContext)
def execution_context(key: UUID, db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
                      user=Depends(require_permission('Execute_ReservationReallocation'))):
    try:
        _, balance, _ = reviewed_stock_scope(db, context, key,
            action='inventory.reservation.reallocate', source_type='sales.reservation')
        settings = read_settings(balance.branch_id, db, context, user)
        if settings.status != 'CONFIGURED': raise ValueError('Complete branch trading settings before reallocation')
        return dict(case_key=key, branch_id=balance.branch_id, branch_version=settings.version)
    except StockRuntimeUnavailable as error:
        raise HTTPException(503, str(error)) from error
    except Exception as error:
        raise translate(error) from error


@ReservationReallocationRouter.post('/{key}/execute', response_model=ReallocationExecutionRead)
def execute_reallocation(key: UUID, payload: ReallocationExecutionRequest, db: Session = Depends(get_db),
                         context: OrgContext = Depends(get_org_context), policy: AccessPolicy = Depends(draft_access),
                         user=Depends(require_permission('Execute_ReservationReallocation'))):
    try:
        binding, balance, authority = reviewed_stock_scope(db, context, key,
            action='inventory.reservation.reallocate', source_type='sales.reservation')
        authorize = guard(policy, 'Execute_ReservationReallocation')
        business_date = require_stock_business_date(db, context, branch_id=balance.branch_id,
            branch_version=payload.branch_version, instant=datetime.now(timezone.utc), authorize=authorize)
        result = reallocate_reservation(db, context, user.id, payload.operation_key,
            case_key=key, binding=binding, business_date=business_date,
            branch_settings_version=payload.branch_version, reason=f'Approved reservation reallocation {key}',
            authority=authority, authorize=authorize)
        db.commit()
        return dict(operation_key=result.operation_key, case_key=key, status='CONSUMED',
            replayed=result.replayed, base_unit=binding.details['base_unit'],
            **{field: result.result[field] for field in ('source_reservation_key',
                'target_reservation_key', 'source_remaining', 'target_remaining')})
    except StockRuntimeUnavailable as error:
        db.rollback(); raise HTTPException(503, str(error)) from error
    except Exception as error:
        db.rollback(); raise translate(error) from error

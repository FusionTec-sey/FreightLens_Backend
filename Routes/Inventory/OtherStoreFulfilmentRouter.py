"""Other-store review requests and decisions; approval never allocates stock."""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid5
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from Model.db import get_db
from Model.containermgmt.Inventory.ManagerCase import ManagerCase
from Schema.OtherStoreFulfilmentSchema import OtherStoreCaseRequest, OtherStoreCaseRead, OwnWorkingStoreRead
from Schema.OtherStoreFulfilmentSchema import OtherStoreExecutionRequest, OtherStoreExecutionRead, OtherStoreExecutionContext
from Services.stock_runtime_service import StockRuntimeUnavailable
from Services.reviewed_stock_runtime_service import reviewed_stock_scope
from Services.stock_ledger_service import reserve_stock
from Services.branch_action_context_service import require_stock_business_date
from Routes.Inventory.BranchSettingsRouter import read_settings
from Services.staff_store_assignment_service import latest_assignment, require_staff_store_assignment
from Schema.SalesReservationSchema import SalesDemandReference
from Schema.ManagerCaseSchema import PolicyCaseReview, CaseActionRead
from Schema.InventoryLocationSchema import LocationPage
from Services.other_store_fulfilment_service import load_other_store_binding
from Services.manager_case_service import CaseBinding, request_case, review_case
from Services.manager_case_read_service import case_page, case_metadata
from Services.sales_reservation_source_service import owned
from Routes.Inventory.ReservationReleaseCaseRouter import guard, translate
from Routes.Orders.SalesIntentRouter import draft_access
from Routes.MasterData.CustomerRouter import private_response
from auth.module_guard import require_module
from auth.policy import AccessPolicy
from auth.security_guards import require_permission
from auth.dependencies import get_org_context, get_current_user
from Utils.org_filter import OrgContext

OtherStoreFulfilmentRouter = APIRouter(prefix='/inventory/other-store-fulfilment-cases',
    tags=['Reservation reviews'], dependencies=[Depends(require_module('INVENTORY')),
        Depends(require_module('SALES')), Depends(draft_access), Depends(private_response)])


@OtherStoreFulfilmentRouter.get('/working-store', response_model=OwnWorkingStoreRead)
def own_working_store(db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
                      user=Depends(require_permission('Request_OtherStoreFulfilment'))):
    try:
        current = latest_assignment(db, context, user.id)
        if current is None: raise PermissionError('Working-store assignment required')
        current = require_staff_store_assignment(db, context, user.id,
            branch_id=current.branch_id, expected_version=current.version)
        return dict(branch_id=current.branch_id, assignment_version=current.version, counter_id=current.counter_id)
    except (PermissionError, LookupError, ValueError) as error:
        raise translate(error) from error


@OtherStoreFulfilmentRouter.post('', response_model=CaseActionRead)
def request_other_store(payload: OtherStoreCaseRequest, db: Session = Depends(get_db),
                        context: OrgContext = Depends(get_org_context), policy: AccessPolicy = Depends(draft_access),
                        user=Depends(require_permission('Request_OtherStoreFulfilment'))):
    try:
        if not db.in_transaction(): db.begin()
        def load(session):
            return load_other_store_binding(session, context, payload.source, requestor_id=user.id,
                assignment_version=payload.assignment_version, balance_id=payload.balance_id,
                expected_stock_version=payload.expected_stock_version, quantity=Decimal(payload.quantity),
                input_unit=payload.input_unit, review_at=payload.review_at)
        result = request_case(db, context, user.id, payload.operation_key, binding=load(db),
            reason=payload.reason, load_binding=load, authorize=guard(policy, 'Request_OtherStoreFulfilment'))
        db.commit()
        return dict(**result.result, replayed=result.replayed)
    except Exception as error:
        db.rollback(); raise translate(error) from error


@OtherStoreFulfilmentRouter.get('', response_model=LocationPage[OtherStoreCaseRead])
def list_other_store(page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
                     view: Literal['ALL', 'MY_REQUESTS', 'NEEDS_MY_REVIEW'] = 'ALL',
                     db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
                     policy: AccessPolicy = Depends(draft_access), user=Depends(get_current_user)):
    if context.org_id not in context.allowed_org_ids: raise HTTPException(403, 'Company denied')
    can_review = policy.has('Review_OtherStoreFulfilment')
    can_execute = policy.has('Execute_OtherStoreFulfilment')
    if not can_review and not can_execute and not policy.has('Request_OtherStoreFulfilment'):
        raise HTTPException(403, 'Other-store review access required')
    query = owned(db, ManagerCase, context).filter_by(action='inventory.fulfilment.other-store', source_type='sales.demand')
    if not can_review and not can_execute: query = query.filter(ManagerCase.created_by == user.id)
    total, rows = case_page(db, query, user.id, view, page, limit)
    fields = ('source', 'selling_branch_id', 'fulfilment_branch_id', 'location_id', 'balance_id',
              'stock_version', 'product_id', 'quantity', 'base_unit', 'input_quantity', 'input_unit',
              'review_at', 'existing_holds')
    items = [dict(**case_metadata(case, decision, used),
        **{key: case.binding['details'][key] for key in fields}) for case, decision, used in rows]
    return dict(items=items, total=total, page=page, limit=limit, pages=max(1, (total+limit-1)//limit))


@OtherStoreFulfilmentRouter.post('/{key}/review', response_model=CaseActionRead)
def review_other_store(key: UUID, payload: PolicyCaseReview, db: Session = Depends(get_db),
                       context: OrgContext = Depends(get_org_context), policy: AccessPolicy = Depends(draft_access),
                       user=Depends(require_permission('Review_OtherStoreFulfilment'))):
    try:
        case = owned(db, ManagerCase, context).filter_by(case_key=key,
            action='inventory.fulfilment.other-store', source_type='sales.demand').one_or_none()
        if case is None: raise LookupError('Case not found')
        binding = CaseBinding(**case.binding); details = binding.details
        result = review_case(db, context, user.id, payload.operation_key, case_key=key, binding=binding,
            expected_version=payload.expected_version, outcome=payload.outcome, reason=payload.reason,
            load_binding=lambda session: load_other_store_binding(session, context,
                SalesDemandReference.model_validate(details['source']), requestor_id=case.created_by,
                assignment_version=details['assignment_version'], balance_id=details['balance_id'],
                expected_stock_version=details['stock_version'], quantity=Decimal(details['input_quantity']),
                input_unit=details['input_unit'], review_at=datetime.fromisoformat(details['review_at'])),
            authorize=guard(policy, 'Review_OtherStoreFulfilment'))
        db.commit()
        return dict(**result.result, replayed=result.replayed)
    except Exception as error:
        db.rollback(); raise translate(error) from error


def execution_scope(db, context, key):
    return reviewed_stock_scope(db, context, key,
        action='inventory.fulfilment.other-store', source_type='sales.demand')


@OtherStoreFulfilmentRouter.get('/{key}/execution-context', response_model=OtherStoreExecutionContext)
def execution_context(key: UUID, db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
                      user=Depends(require_permission('Execute_OtherStoreFulfilment'))):
    try:
        _, balance, _ = execution_scope(db, context, key)
        settings = read_settings(balance.branch_id, db, context, user)
        if settings.status != 'CONFIGURED': raise ValueError('Complete target-store trading settings before allocation')
        return dict(case_key=key, branch_id=balance.branch_id, branch_version=settings.version)
    except StockRuntimeUnavailable as error:
        raise HTTPException(503, str(error)) from error
    except Exception as error:
        raise translate(error) from error


@OtherStoreFulfilmentRouter.post('/{key}/execute', response_model=OtherStoreExecutionRead)
def execute_other_store(key: UUID, payload: OtherStoreExecutionRequest, db: Session = Depends(get_db),
                        context: OrgContext = Depends(get_org_context), policy: AccessPolicy = Depends(draft_access),
                        user=Depends(require_permission('Execute_OtherStoreFulfilment'))):
    try:
        binding, balance, authority = execution_scope(db, context, key)
        details = binding.details
        authorize = guard(policy, 'Execute_OtherStoreFulfilment')
        business_date = require_stock_business_date(db, context, branch_id=balance.branch_id,
            branch_version=payload.branch_version, instant=datetime.now(timezone.utc), authorize=authorize)
        source = SalesDemandReference.model_validate(details['source'])
        result = reserve_stock(db, context, user.id, payload.operation_key,
            balance_id=balance.id, reservation_key=uuid5(key, 'approved-other-store-hold'),
            source_line_key=source.stock_source_key(), quantity=Decimal(details['input_quantity']),
            input_unit=details['input_unit'], review_at=datetime.fromisoformat(details['review_at']),
            reason=f'Approved other-store allocation {key}', business_date=business_date,
            branch_settings_version=payload.branch_version, authority=authority, authorize=authorize,
            sales_source=source, other_store_case_key=key, other_store_binding=binding)
        db.commit()
        return dict(operation_key=result.operation_key, case_key=key, status='CONSUMED',
            reservation_key=result.result['reservation_key'], branch_id=balance.branch_id,
            location_id=balance.location_id, quantity=details['quantity'], base_unit=details['base_unit'],
            replayed=result.replayed)
    except StockRuntimeUnavailable as error:
        db.rollback(); raise HTTPException(503, str(error)) from error
    except Exception as error:
        db.rollback(); raise translate(error) from error

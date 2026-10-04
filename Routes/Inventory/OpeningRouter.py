"""Reviewed opening/import cases; never accepts a legacy product stock total."""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from Model.db import get_db
from Model.containermgmt.Inventory.ManagerCase import ManagerCase
from Schema.InventoryLocationSchema import LocationPage
from Schema.InventoryOpeningSchema import (
    InventoryOpeningCaseRead, InventoryOpeningExecute,
    InventoryOpeningExecutionRead, InventoryOpeningInput,
    InventoryOpeningRequest)
from Schema.ManagerCaseSchema import CaseActionRead, PolicyCaseReview
from Services.cost_runtime_service import CostRuntimeUnavailable, server_cost_runtime
from Services.inventory_opening_case_service import (
    ACTION, SOURCE_TYPE, execute_reviewed_opening, opening_binding,
    reload_opening_binding)
from Services.inventory_posting_service import PostingConflict
from Services.manager_case_read_service import case_metadata, case_page
from Services.manager_case_service import CaseBinding, request_case, review_case
from Services.stock_runtime_service import StockRuntimeUnavailable, server_stock_runtime
from Utils.org_filter import OrgContext, apply_org_filter
from auth.dependencies import get_current_user, get_org_context
from auth.module_guard import require_module
from auth.policy import AccessPolicy, get_request_policy
from auth.security_guards import is_financial_user, require_permission


OpeningRouter = APIRouter(prefix='/inventory/opening-cases',
    tags=['Inventory opening and import'],
    dependencies=[Depends(require_module('INVENTORY'))])


def translate(error):
    if isinstance(error, HTTPException): return error
    if isinstance(error, LookupError): return HTTPException(404, str(error))
    if isinstance(error, PermissionError): return HTTPException(403, str(error))
    if isinstance(error, PostingConflict): return HTTPException(409, str(error))
    if isinstance(error, ValueError): return HTTPException(422, str(error))
    return error


def access(context, user, policy, permission):
    required = {permission, 'View_Product', 'View_Financials',
        'Manage_Financials'}
    if (not all(policy.has(name) for name in required)
            or not is_financial_user(user, context)):
        raise PermissionError('Reviewed opening/import financial access required')
    if permission == 'Execute_InventoryOpening' \
            and not policy.has('Post_InventoryCost'):
        raise PermissionError('Inventory cost-posting permission required')


def guard(context, user, policy, permission):
    def authorize(db):
        access(context, user, policy, permission)
    return authorize


def scoped_cases(db, context):
    return apply_org_filter(db.query(ManagerCase).filter(
        ManagerCase.org_id == context.org_id,
        ManagerCase.is_deleted.is_(False),
        ManagerCase.action == ACTION,
        ManagerCase.source_type == SOURCE_TYPE), ManagerCase, context)


@OpeningRouter.post('', response_model=CaseActionRead)
def request_opening(payload: InventoryOpeningRequest,
        db: Session = Depends(get_db),
        context: OrgContext = Depends(get_org_context),
        policy: AccessPolicy = Depends(get_request_policy),
        user=Depends(require_permission('Request_InventoryOpening'))):
    try:
        access(context, user, policy, 'Request_InventoryOpening')
        intent = InventoryOpeningInput.model_validate(
            payload.model_dump(exclude={'operation_key'}))
        binding = opening_binding(db, context, intent, lock=True)
        result = request_case(db, context, user.id, payload.operation_key,
            binding=binding, reason=payload.reason,
            load_binding=lambda session: opening_binding(
                session, context, intent, lock=True),
            authorize=guard(context, user, policy,
                'Request_InventoryOpening'))
        db.commit()
        return CaseActionRead(**result.result, replayed=result.replayed)
    except Exception as error:
        db.rollback(); raise translate(error) from error


@OpeningRouter.get('', response_model=LocationPage[InventoryOpeningCaseRead])
def list_openings(page: int = Query(1, ge=1),
        limit: int = Query(25, ge=1, le=100),
        view: Literal['ALL', 'NEEDS_MY_REVIEW', 'MY_REQUESTS'] = 'ALL',
        db: Session = Depends(get_db),
        context: OrgContext = Depends(get_org_context),
        policy: AccessPolicy = Depends(get_request_policy),
        user=Depends(get_current_user)):
    permissions = {'Request_InventoryOpening', 'Review_InventoryOpening',
        'Execute_InventoryOpening'}
    available = [name for name in permissions if policy.has(name)]
    if not available:
        raise HTTPException(403, 'Opening/import access required')
    try:
        access(context, user, policy, available[0])
    except Exception as error:
        raise translate(error) from error
    query = scoped_cases(db, context)
    if not (policy.has('Review_InventoryOpening')
            or policy.has('Execute_InventoryOpening')):
        query = query.filter(ManagerCase.created_by == user.id)
    total, rows = case_page(db, query, user.id, view, page, limit)
    items = []
    for case, decision, used in rows:
        details = case.binding['details']
        items.append(InventoryOpeningCaseRead(
            **case_metadata(case, decision, used),
            **{name: details[name] for name in (
                'source_key', 'branch_id', 'location_id', 'product_id',
                'product_name', 'base_unit', 'tracking_policy',
                'expected_policy_version', 'expected_valuation_version',
                'on_hand', 'damaged', 'quarantined', 'goods_value_scr',
                'additional_cost_scr')}))
    return {'items': items, 'total': total, 'page': page, 'limit': limit,
        'pages': max(1, (total + limit - 1) // limit)}


@OpeningRouter.post('/{case_key}/review', response_model=CaseActionRead)
def review_opening(case_key: UUID, payload: PolicyCaseReview,
        db: Session = Depends(get_db),
        context: OrgContext = Depends(get_org_context),
        policy: AccessPolicy = Depends(get_request_policy),
        user=Depends(require_permission('Review_InventoryOpening'))):
    try:
        access(context, user, policy, 'Review_InventoryOpening')
        case = scoped_cases(db, context).filter(
            ManagerCase.case_key == case_key).one_or_none()
        if case is None:
            raise LookupError('Opening/import case not found')
        binding = CaseBinding(**case.binding)
        result = review_case(db, context, user.id, payload.operation_key,
            case_key=case_key, binding=binding,
            expected_version=payload.expected_version,
            outcome=payload.outcome, reason=payload.reason,
            load_binding=lambda session: reload_opening_binding(
                session, context, binding),
            authorize=guard(context, user, policy,
                'Review_InventoryOpening'))
        db.commit()
        return CaseActionRead(**result.result, replayed=result.replayed)
    except Exception as error:
        db.rollback(); raise translate(error) from error


@OpeningRouter.post('/{case_key}/execute',
    response_model=InventoryOpeningExecutionRead)
def execute_opening(case_key: UUID, payload: InventoryOpeningExecute,
        db: Session = Depends(get_db),
        context: OrgContext = Depends(get_org_context),
        policy: AccessPolicy = Depends(get_request_policy),
        user=Depends(require_permission('Execute_InventoryOpening'))):
    try:
        access(context, user, policy, 'Execute_InventoryOpening')
        case = scoped_cases(db, context).filter(
            ManagerCase.case_key == case_key).one_or_none()
        if case is None:
            raise LookupError('Opening/import case not found')
        binding = CaseBinding(**case.binding)
        stock_claim = server_stock_runtime().claim_for(
            db, context, binding.details['branch_id'])
        cost_claim = server_cost_runtime().claim_for(
            db, context, binding.details['cost_pool_id'])
        result = execute_reviewed_opening(db, context, user.id,
            payload.operation_key, case_key=case_key, binding=binding,
            stock_authority=stock_claim, cost_authority=cost_claim,
            authorize_stock=guard(context, user, policy,
                'Execute_InventoryOpening'),
            authorize_cost=guard(context, user, policy,
                'Execute_InventoryOpening'))
        db.commit()
        return InventoryOpeningExecutionRead(operation_key=result.operation_key,
            case_key=case_key, replayed=result.replayed, **result.result)
    except (StockRuntimeUnavailable, CostRuntimeUnavailable) as error:
        db.rollback(); raise HTTPException(503, str(error)) from error
    except Exception as error:
        db.rollback(); raise translate(error) from error

"""Cross-module customer master; explicit customer AND personal-data access.

No sales entitlement, credit, balance, merging or messaging capability.
"""
from uuid import UUID
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session
from Model.db import get_db
from Model.containermgmt.MasterData.RetailCustomer import RetailCustomer
from Schema.CustomerSchema import CustomerIdentityRead, CustomerCreateRequest, CustomerCreated, CustomerSearchRequest
from Schema.CustomerSchema import CustomerProfileUpdate, CustomerProfileSaved, CustomerProfileHistory
from Services.customer_profile_service import current_profiles_for_page, update_customer_profile, customer_profile_history
from Schema.CustomerDuplicateSchema import CustomerDuplicateRequest, CustomerDuplicateRead
from Schema.ManagerCaseSchema import PolicyCaseReview, CaseActionRead
from Services.customer_duplicate_service import request_duplicate_review, review_duplicate, ACTION, SOURCE
from Services.manager_case_read_service import case_page, case_metadata
from Model.containermgmt.Inventory.ManagerCase import ManagerCase
from Schema.InventoryLocationSchema import LocationPage
from Services.customer_identity_service import create_customer, get_customer
from Services.inventory_posting_service import PostingConflict
from Utils.org_filter import OrgContext, apply_org_filter
from auth.dependencies import get_org_context, get_current_user
from auth.security_guards import require_permission
from auth.policy import AccessPolicy, get_request_policy
from Services.search_service import search_customers, sync_customer_document, CustomerSearchUnavailable


def customer_access(policy: AccessPolicy = Depends(get_request_policy)):
    if not policy.has('View_Customer') or not policy.has('View_Personal_Data') or not policy.allows_field_class('PERSONAL'):
        raise HTTPException(403, 'Customer and personal-data access required')
    return policy


def private_response(response: Response):
    response.headers['Cache-Control'] = 'no-store'


CustomerRouter = APIRouter(prefix='/master-data/customers', tags=['Customers'],
                          dependencies=[Depends(customer_access), Depends(private_response)])


def scoped_customers(db, context):
    if context.org_id not in context.allowed_org_ids:
        raise HTTPException(403, 'Select an allowed company')
    return apply_org_filter(db.query(RetailCustomer).filter_by(org_id=context.org_id,
        is_deleted=False), RetailCustomer, context)


@CustomerRouter.get('', response_model=LocationPage[CustomerIdentityRead])
def list_customers(request: Request, page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
                   db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context)):
    if 'search' in request.query_params:
        raise HTTPException(422, 'Use the private search request body, not URL parameters')
    return customer_page(db, context, page, limit)


@CustomerRouter.post('/search', response_model=LocationPage[CustomerIdentityRead])
def find_customers(payload: CustomerSearchRequest, db: Session = Depends(get_db),
                   context: OrgContext = Depends(get_org_context)):
    # Read-only operation: no receipt, audit event, or creation permission needed.
    return customer_page(db, context, payload.page, payload.limit, payload.search)


def customer_page(db, context, page, limit, search=''):
    query = scoped_customers(db, context)
    if search.strip():
        try:
            keys, total = search_customers(search.strip(), context.org_id, page, limit)
            found = {row.customer_key: row for row in query.filter(RetailCustomer.customer_key.in_(keys)).all()} if keys else {}
            if len(found) != len(keys):
                raise CustomerSearchUnavailable('Customer search needs refresh; retry or clear search')
            rows = [found[key] for key in keys]
        except CustomerSearchUnavailable as error:
            raise HTTPException(503, str(error)) from error
    else:
        total = query.count()
        rows = query.order_by(RetailCustomer.customer_key).offset((page - 1) * limit).limit(limit).all()
    return dict(items=current_profiles_for_page(db, context, rows), total=total,
                page=page, limit=limit, pages=max(1, (total + limit - 1) // limit))


@CustomerRouter.get('/{key}', response_model=CustomerIdentityRead)
def read_customer(key: UUID, version: int | None = Query(None, ge=1), db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
                  policy: AccessPolicy = Depends(customer_access)):
    try:
        return get_customer(db, context, key, version=version, authorize=lambda session: customer_access(policy))
    except LookupError as error: raise HTTPException(404, 'Customer not found') from error
    except PermissionError as error: raise HTTPException(403, str(error)) from error


@CustomerRouter.post('', response_model=CustomerCreated)
def add_customer(payload: CustomerCreateRequest, db: Session = Depends(get_db),
                 context: OrgContext = Depends(get_org_context), policy: AccessPolicy = Depends(customer_access),
                 user=Depends(require_permission('Manage_Customer'))):
    def authorize(session):
        customer_access(policy)
        if not policy.has('Manage_Customer'): raise PermissionError('Customer creation access required')
    try:
        if not db.in_transaction(): db.begin()
        outcome = create_customer(db, context, user.id, payload.operation_key, payload.profile,
                                  expected_version=payload.expected_version, authorize=authorize)
        db.commit()
        # Projection failure never changes the committed receipt. Exact retries
        # also repair indexing; startup repair handles an interrupted sync.
        current = get_customer(db, context, payload.operation_key, authorize=authorize)
        profile = current.model_dump(mode='json', exclude={'customer_key', 'version'})
        db.rollback()  # End projection read before external search I/O.
        indexed = sync_customer_document(payload.operation_key, context.org_id, profile)
        return dict(**outcome.result, replayed=outcome.replayed, search_indexed=indexed)
    except Exception as error:
        db.rollback()
        if isinstance(error, PostingConflict): raise HTTPException(409, str(error)) from error
        if isinstance(error, PermissionError): raise HTTPException(403, str(error)) from error
        if isinstance(error, ValueError): raise HTTPException(422, str(error)) from error
        raise


@CustomerRouter.get('/{key}/history', response_model=LocationPage[CustomerProfileHistory])
def profile_history(key: UUID, page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
                    db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
                    policy: AccessPolicy = Depends(customer_access)):
    try:
        return customer_profile_history(db, context, key, page=page, limit=limit,
            authorize=lambda session: customer_access(policy))
    except LookupError as error: raise HTTPException(404, 'Customer not found') from error
    except PermissionError as error: raise HTTPException(403, str(error)) from error


@CustomerRouter.put('/{key}/profile', response_model=CustomerProfileSaved)
def edit_customer_profile(key: UUID, payload: CustomerProfileUpdate,
                          db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
                          policy: AccessPolicy = Depends(customer_access),
                          user=Depends(require_permission('Manage_Customer'))):
    def authorize(session):
        customer_access(policy)
        if not policy.has('Manage_Customer'):
            raise PermissionError('Customer management access required')
    try:
        if not db.in_transaction(): db.begin()
        outcome = update_customer_profile(db, context, user.id, key, payload, authorize=authorize)
        db.commit()
        current = get_customer(db, context, key, authorize=authorize)
        profile = current.model_dump(mode='json', exclude={'customer_key', 'version'})
        db.rollback()
        indexed = sync_customer_document(key, context.org_id, profile)
        return dict(**outcome.result, replayed=outcome.replayed, search_indexed=indexed)
    except Exception as error:
        db.rollback()
        if isinstance(error, PostingConflict): raise HTTPException(409, str(error)) from error
        if isinstance(error, LookupError): raise HTTPException(404, 'Customer not found') from error
        if isinstance(error, PermissionError): raise HTTPException(403, str(error)) from error
        if isinstance(error, ValueError): raise HTTPException(422, str(error)) from error
        raise


def duplicate_guard(policy, permission):
    def authorize(session):
        customer_access(policy)
        if not policy.has(permission):
            raise PermissionError('Customer duplicate-review permission required')
    return authorize


def duplicate_error(error):
    if isinstance(error, LookupError): return HTTPException(404, 'Customer or review not found')
    if isinstance(error, PermissionError): return HTTPException(403, str(error))
    if isinstance(error, PostingConflict): return HTTPException(409, str(error))
    if isinstance(error, ValueError): return HTTPException(422, str(error))
    return error


@CustomerRouter.post('/duplicates/cases', response_model=CaseActionRead)
def request_duplicate(payload: CustomerDuplicateRequest, db: Session = Depends(get_db),
                      context: OrgContext = Depends(get_org_context),
                      policy: AccessPolicy = Depends(customer_access),
                      user=Depends(require_permission('Request_CustomerDuplicate'))):
    try:
        if not db.in_transaction(): db.begin()
        result = request_duplicate_review(db, context, user.id, payload,
            authorize=duplicate_guard(policy, 'Request_CustomerDuplicate'))
        db.commit()
        return dict(**result.result, replayed=result.replayed)
    except Exception as error:
        db.rollback(); raise duplicate_error(error) from error


@CustomerRouter.get('/duplicates/cases', response_model=LocationPage[CustomerDuplicateRead])
def list_duplicate_cases(page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
                         view: Literal['ALL', 'MY_REQUESTS', 'NEEDS_MY_REVIEW'] = 'ALL',
                         db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
                         policy: AccessPolicy = Depends(customer_access), user=Depends(get_current_user)):
    if context.org_id not in context.allowed_org_ids: raise HTTPException(403, 'Company denied')
    can_review = policy.has('Review_CustomerDuplicate')
    if not can_review and not policy.has('Request_CustomerDuplicate'):
        raise HTTPException(403, 'Customer duplicate-review access required')
    query = apply_org_filter(db.query(ManagerCase).filter_by(org_id=context.org_id,
        action=ACTION, source_type=SOURCE, is_deleted=False), ManagerCase, context)
    if not can_review: query = query.filter(ManagerCase.created_by == user.id)
    total, rows = case_page(db, query, user.id, view, page, limit)
    items = [dict(**case_metadata(case, decision, used),
        customers=case.binding['details']['customers'], assessment=case.binding['details']['assessment'],
        merge_authorized=False) for case, decision, used in rows]
    return dict(items=items, total=total, page=page, limit=limit, pages=max(1, (total + limit - 1) // limit))


@CustomerRouter.post('/duplicates/cases/{key}/review', response_model=CaseActionRead)
def decide_duplicate(key: UUID, payload: PolicyCaseReview, db: Session = Depends(get_db),
                     context: OrgContext = Depends(get_org_context), policy: AccessPolicy = Depends(customer_access),
                     user=Depends(require_permission('Review_CustomerDuplicate'))):
    try:
        if not db.in_transaction(): db.begin()
        result = review_duplicate(db, context, user.id, payload.operation_key,
            case_key=key, expected_version=payload.expected_version, outcome=payload.outcome,
            reason=payload.reason, authorize=duplicate_guard(policy, 'Review_CustomerDuplicate'))
        db.commit()
        return dict(**result.result, replayed=result.replayed)
    except Exception as error:
        db.rollback(); raise duplicate_error(error) from error

"""Cross-module customer master; explicit customer AND personal-data access.

No sales entitlement, credit, balance, merging or messaging capability.
"""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session
from Model.db import get_db
from Model.containermgmt.MasterData.RetailCustomer import RetailCustomer
from Schema.CustomerSchema import CustomerIdentityRead, CustomerCreateRequest, CustomerCreated, CustomerSearchRequest
from Schema.InventoryLocationSchema import LocationPage
from Services.customer_identity_service import create_customer, get_customer
from Services.inventory_posting_service import PostingConflict
from Utils.org_filter import OrgContext, apply_org_filter
from auth.dependencies import get_org_context
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
    return dict(items=[CustomerIdentityRead(**row.initial_profile, customer_key=row.customer_key, version=1)
                       for row in rows], total=total, page=page, limit=limit, pages=max(1, (total + limit - 1) // limit))


@CustomerRouter.get('/{key}', response_model=CustomerIdentityRead)
def read_customer(key: UUID, db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
                  policy: AccessPolicy = Depends(customer_access)):
    try:
        return get_customer(db, context, key, authorize=lambda session: customer_access(policy))
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
        indexed = sync_customer_document(payload.operation_key, context.org_id, payload.profile.model_dump(mode='json'))
        return dict(**outcome.result, replayed=outcome.replayed, search_indexed=indexed)
    except Exception as error:
        db.rollback()
        if isinstance(error, PostingConflict): raise HTTPException(409, str(error)) from error
        if isinstance(error, PermissionError): raise HTTPException(403, str(error)) from error
        if isinstance(error, ValueError): raise HTTPException(422, str(error)) from error
        raise

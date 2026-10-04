"""Retail sales drafts only. SALES entitlement never grants financial posting."""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from Model.db import get_db
from Model.containermgmt.Orders.SalesIntent import SalesIntentRevision, SalesIntentLineRevision
from Model.containermgmt.MasterData.RetailCustomer import RetailCustomer
from Model.containermgmt.Inventory.Location import InventoryBranch
from Schema.SalesIntentSchema import SalesIntentSave, SalesIntentSaved, SalesIntentRead, SalesIntentSummary
from Schema.SalesAreaPreviewSchema import SalesAreaPreview, LocalDraftReserveRequest, LocalDraftReserveReceipt
from Schema.InventoryLocationSchema import LocationPage
from Services.sales_intent_service import save_sales_intent, get_sales_intent
from Services.sales_area_preview_service import preview_sales_area
from Services.sales_local_reservation_service import reserve_local_draft
from Services.inventory_posting_service import PostingConflict
from Routes.MasterData.CustomerRouter import customer_access, private_response
from Utils.org_filter import OrgContext, apply_org_filter
from auth.dependencies import get_org_context
from auth.policy import AccessPolicy
from auth.security_guards import require_permission
from auth.module_guard import require_module


def draft_access(policy: AccessPolicy = Depends(customer_access)):
    if not policy.has('View_SalesDraft') or not policy.has('View_Product'):
        raise HTTPException(403, 'Sales draft and product access required')
    return policy


SalesIntentRouter = APIRouter(prefix='/sales/drafts', tags=['Sales drafts'], dependencies=[
    Depends(require_module('SALES')), Depends(draft_access), Depends(private_response)])


@SalesIntentRouter.get('', response_model=LocationPage[SalesIntentSummary])
def list_drafts(page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
                db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context)):
    if context.org_id not in context.allowed_org_ids: raise HTTPException(403, 'Select an allowed company')
    model = SalesIntentRevision
    latest = apply_org_filter(db.query(model.document_key, func.max(model.version).label('version')).filter_by(
        org_id=context.org_id, is_deleted=False), model, context).group_by(model.document_key).subquery()
    query = db.query(model).join(latest, (model.document_key == latest.c.document_key) &
        (model.version == latest.c.version)).filter(model.org_id == context.org_id, model.is_deleted.is_(False))
    total = query.count()
    # Register labels only: the customer name needs the personal-data entitlement
    # this router already enforces, and no supplier, cost or price is exposed.
    lines = db.query(SalesIntentLineRevision.document_key, SalesIntentLineRevision.version,
        func.count().label('line_count')).filter(SalesIntentLineRevision.org_id == context.org_id,
        SalesIntentLineRevision.is_deleted.is_(False)).group_by(
            SalesIntentLineRevision.document_key, SalesIntentLineRevision.version).subquery()
    rows = query.add_columns(RetailCustomer.initial_profile['name'].astext.label('customer_name'),
        InventoryBranch.name.label('branch_name'), func.coalesce(lines.c.line_count, 0).label('line_count')) \
        .outerjoin(RetailCustomer, (RetailCustomer.org_id == model.org_id) &
            (RetailCustomer.customer_key == model.customer_key) & (RetailCustomer.is_deleted.is_(False))) \
        .outerjoin(InventoryBranch, (InventoryBranch.org_id == model.org_id) &
            (InventoryBranch.id == model.branch_id) & (InventoryBranch.is_deleted.is_(False))) \
        .outerjoin(lines, (lines.c.document_key == model.document_key) & (lines.c.version == model.version)) \
        .order_by(model.created_at.desc(), model.document_key).offset((page - 1) * limit).limit(limit).all()
    return dict(items=[dict(document_key=row[0].document_key, version=row[0].version, status=row[0].status,
        customer_key=row[0].customer_key, branch_id=row[0].branch_id, customer_name=row.customer_name,
        branch_name=row.branch_name, created_at=row[0].created_at, line_count=row.line_count)
        for row in rows], total=total, page=page, limit=limit, pages=max(1, (total + limit - 1) // limit))


@SalesIntentRouter.get('/{key}', response_model=SalesIntentRead)
def read_draft(key: UUID, db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
               policy: AccessPolicy = Depends(draft_access)):
    try:
        return get_sales_intent(db, context, key, authorize=lambda session: draft_access(policy))
    except LookupError as error: raise HTTPException(404, 'Sales draft not found') from error
    except PermissionError as error: raise HTTPException(403, str(error)) from error


@SalesIntentRouter.get('/{key}/work-area-preview', response_model=SalesAreaPreview)
def read_work_area_preview(key: UUID, counter_key: UUID, db: Session = Depends(get_db),
                           context: OrgContext = Depends(get_org_context),
                           policy: AccessPolicy = Depends(draft_access)):
    try:
        return preview_sales_area(db, context, key, counter_key,
            authorize=lambda session: draft_access(policy))
    except LookupError as error: raise HTTPException(404, str(error)) from error
    except PermissionError as error: raise HTTPException(403, str(error)) from error
    except ValueError as error: raise HTTPException(409, str(error)) from error


@SalesIntentRouter.post('/{key}/reserve-local', response_model=LocalDraftReserveReceipt,
    dependencies=[Depends(require_module('INVENTORY'))])
def reserve_local(key: UUID, payload: LocalDraftReserveRequest, db: Session = Depends(get_db),
                  context: OrgContext = Depends(get_org_context), policy: AccessPolicy = Depends(draft_access),
                  user=Depends(require_permission('Reserve_SalesDraft'))):
    def authorize(session):
        draft_access(policy)
        if not policy.has('Reserve_SalesDraft'): raise PermissionError('Sales reservation access required')
    try:
        if not db.in_transaction(): db.begin()
        result = reserve_local_draft(db, context, user.id, key, payload, authorize=authorize)
        db.commit()
        return result
    except Exception as error:
        db.rollback()
        if isinstance(error, PostingConflict): raise HTTPException(409, str(error)) from error
        if isinstance(error, LookupError): raise HTTPException(404, str(error)) from error
        if isinstance(error, PermissionError): raise HTTPException(403, str(error)) from error
        if isinstance(error, ValueError): raise HTTPException(422, str(error)) from error
        raise


@SalesIntentRouter.put('/{key}', response_model=SalesIntentSaved)
def save_draft(key: UUID, payload: SalesIntentSave, db: Session = Depends(get_db),
               context: OrgContext = Depends(get_org_context), policy: AccessPolicy = Depends(draft_access),
               user=Depends(require_permission('Manage_SalesDraft'))):
    def authorize(session):
        draft_access(policy)
        if not policy.has('Manage_SalesDraft'): raise PermissionError('Sales draft write access required')
    try:
        if not db.in_transaction(): db.begin()
        result = save_sales_intent(db, context, user.id, payload.operation_key, key, payload.draft,
            expected_version=payload.expected_version, authorize=authorize)
        db.commit()
        return dict(**result.result, replayed=result.replayed)
    except Exception as error:
        db.rollback()
        if isinstance(error, PostingConflict): raise HTTPException(409, str(error)) from error
        if isinstance(error, LookupError): raise HTTPException(404, 'Draft or source not found') from error
        if isinstance(error, PermissionError): raise HTTPException(403, str(error)) from error
        if isinstance(error, ValueError): raise HTTPException(422, str(error)) from error
        raise

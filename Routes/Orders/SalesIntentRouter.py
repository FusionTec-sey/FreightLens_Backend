"""Retail sales drafts only. SALES entitlement never grants financial posting."""
from datetime import datetime, timezone
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Path
from sqlalchemy.orm import Session
from sqlalchemy import func
from Model.db import get_db
from Model.containermgmt.Orders.SalesIntent import SalesIntentRevision
from Schema.SalesIntentSchema import SalesIntentSave, SalesIntentSaved, SalesIntentRead, SalesIntentSummary, SalesIntentHistoryItem
from Schema.SalesIntentSchema import SalesIntentHistoryDetail
from Schema.SalesPricingSchema import (
    SalesPricingPreviewRead, SalesTransactionPricingPrepare,
    SalesTransactionPricingRead,
)
from Schema.InventoryLocationSchema import LocationPage
from Services.sales_intent_service import save_sales_intent, get_sales_intent, sales_branch_labels
from Services.customer_profile_service import historical_names_for_page
from Services.inventory_posting_service import PostingConflict
from Services.search_service import search_sales_drafts, SalesSearchUnavailable
from Services.sales_draft_search_projection import project_sales_draft
from Services.sales_pricing_preview_service import (
    PricingUnavailable, preview_sales_pricing,
)
from Services.sales_transaction_pricing_service import (
    latest_transaction_pricing, prepare_transaction_pricing,
)
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
                branch_id: int | None = Query(None, gt=0),
                search: str = Query('', max_length=160),
                db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
                policy: AccessPolicy = Depends(draft_access)):
    if context.org_id not in context.allowed_org_ids: raise HTTPException(403, 'Select an allowed company')
    model = SalesIntentRevision
    latest = apply_org_filter(db.query(model.document_key, func.max(model.version).label('version')).filter_by(
        org_id=context.org_id, is_deleted=False), model, context).group_by(model.document_key).subquery()
    query = db.query(model).join(latest, (model.document_key == latest.c.document_key) &
        (model.version == latest.c.version)).filter(model.org_id == context.org_id, model.is_deleted.is_(False))
    if branch_id is not None:
        query = query.filter(model.branch_id == branch_id)
    if search.strip():
        try:
            hits, total = search_sales_drafts(search.strip(), context.org_id, page, limit, branch_id)
            candidates = query.filter(model.document_key.in_([key for key, _, _ in hits])).all() if hits else []
            by_key = {row.document_key: row for row in candidates}
            if any(key not in by_key or by_key[key].version != version or
                   by_key[key].branch_id != branch for key, version, branch in hits):
                raise SalesSearchUnavailable('Sales search is out of date; retry or clear search')
            rows = [by_key[key] for key, _, _ in hits]
        except SalesSearchUnavailable as error:
            raise HTTPException(503, str(error)) from error
    else:
        total = query.count()
        rows = query.order_by(model.created_at.desc(), model.document_key).offset((page - 1) * limit).limit(limit).all()
    # Only project labels for this page; never load the full branch catalogue.
    names = sales_branch_labels(db, context, [row.branch_id for row in rows])
    customer_names = historical_names_for_page(db, context,
        [(row.customer_key, row.customer_version) for row in rows], authorize=lambda session: draft_access(policy))
    return dict(items=[dict(document_key=row.document_key, version=row.version, status=row.status,
        customer_key=row.customer_key, customer_name=customer_names.get((row.customer_key, row.customer_version)),
        branch_id=row.branch_id, branch_name=names.get(row.branch_id)) for row in rows], total=total,
        page=page, limit=limit, pages=max(1, (total + limit - 1) // limit))


@SalesIntentRouter.get('/{key}', response_model=SalesIntentRead)
def read_draft(key: UUID, db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
               policy: AccessPolicy = Depends(draft_access)):
    try:
        return get_sales_intent(db, context, key, authorize=lambda session: draft_access(policy))
    except LookupError as error: raise HTTPException(404, 'Sales draft not found') from error
    except PermissionError as error: raise HTTPException(403, str(error)) from error


@SalesIntentRouter.get('/{key}/pricing-preview', response_model=SalesPricingPreviewRead)
def pricing_preview(key: UUID, db: Session = Depends(get_db),
                    context: OrgContext = Depends(get_org_context),
                    policy: AccessPolicy = Depends(draft_access)):
    """Current configuration preview only; never posts or freezes a sale."""
    authorize = lambda session: draft_access(policy)
    try:
        draft = get_sales_intent(db, context, key, authorize=authorize)
        return preview_sales_pricing(db, context, draft,
            priced_at=datetime.now(timezone.utc), authorize=authorize)
    except PricingUnavailable as error:
        raise HTTPException(409,
            f'Pricing configuration incomplete: {error}') from error
    except LookupError as error:
        raise HTTPException(404, 'Sales draft not found') from error
    except PermissionError as error:
        raise HTTPException(403, str(error)) from error


@SalesIntentRouter.post('/{key}/pricing-snapshots',
    response_model=SalesTransactionPricingRead)
def prepare_pricing_snapshot(key: UUID, payload: SalesTransactionPricingPrepare,
                             db: Session = Depends(get_db),
                             context: OrgContext = Depends(get_org_context),
                             policy: AccessPolicy = Depends(draft_access),
                             user=Depends(require_permission('Manage_SalesDraft'))):
    """Prepare exact future posting inputs; never creates or posts a sale."""
    def authorize(session):
        draft_access(policy)
        if not policy.has('Manage_SalesDraft'):
            raise PermissionError('Sales draft write access required')
    try:
        if not db.in_transaction():
            db.begin()
        result = prepare_transaction_pricing(db, context, user.id, key,
            payload, authorize=authorize)
        db.commit()
        return result
    except Exception as error:
        db.rollback()
        if isinstance(error, PostingConflict):
            raise HTTPException(409, str(error)) from error
        if isinstance(error, LookupError):
            raise HTTPException(404, str(error)) from error
        if isinstance(error, PermissionError):
            raise HTTPException(403, str(error)) from error
        if isinstance(error, (ValueError, PricingUnavailable)):
            raise HTTPException(422, str(error)) from error
        raise


@SalesIntentRouter.get('/{key}/pricing-snapshots/latest',
    response_model=SalesTransactionPricingRead)
def latest_pricing_snapshot(key: UUID,
                            draft_version: int | None = Query(None, ge=1),
                            db: Session = Depends(get_db),
                            context: OrgContext = Depends(get_org_context),
                            policy: AccessPolicy = Depends(draft_access)):
    try:
        return latest_transaction_pricing(db, context, key,
            draft_version=draft_version,
            authorize=lambda session: draft_access(policy))
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except PermissionError as error:
        raise HTTPException(403, str(error)) from error


@SalesIntentRouter.get('/{key}/history', response_model=LocationPage[SalesIntentHistoryItem])
def draft_history(key: UUID, page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
                  db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
                  policy: AccessPolicy = Depends(draft_access)):
    if context.org_id not in context.allowed_org_ids:
        raise HTTPException(403, 'Select an allowed company')
    model = SalesIntentRevision
    # Existing unique (org_id, document_key, version) index serves this history.
    query = apply_org_filter(db.query(model).filter(model.org_id == context.org_id,
        model.document_key == key, model.is_deleted.is_(False)), model, context)
    total = query.count()
    if not total:
        raise HTTPException(404, 'Sales draft not found')
    rows = query.order_by(model.version.desc()).offset((page - 1) * limit).limit(limit).all()
    names = historical_names_for_page(db, context,
        [(row.customer_key, row.customer_version) for row in rows], authorize=lambda session: draft_access(policy))
    return dict(items=[dict(document_key=row.document_key, version=row.version, status=row.status,
        customer_key=row.customer_key, customer_version=row.customer_version,
        customer_name=names.get((row.customer_key, row.customer_version)), branch_id=row.branch_id,
        created_at=row.created_at, created_by=row.created_by) for row in rows],
        total=total, page=page, limit=limit, pages=max(1, (total + limit - 1) // limit))


@SalesIntentRouter.get('/{key}/history/{version}', response_model=SalesIntentHistoryDetail)
def read_draft_revision(key: UUID, version: int = Path(ge=1),
                        db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
                        policy: AccessPolicy = Depends(draft_access)):
    try:
        return get_sales_intent(db, context, key, version=version,
                                authorize=lambda session: draft_access(policy))
    except LookupError as error:
        raise HTTPException(404, 'Sales draft revision not found') from error
    except PermissionError as error:
        raise HTTPException(403, str(error)) from error


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
            expected_version=payload.expected_version, authorize=authorize,
            source_reference=payload.source_reference)
        db.commit()
        indexed = project_sales_draft(db, context, key, authorize=authorize)
        return dict(**result.result, replayed=result.replayed, search_indexed=indexed)
    except Exception as error:
        db.rollback()
        if isinstance(error, PostingConflict): raise HTTPException(409, str(error)) from error
        if isinstance(error, LookupError): raise HTTPException(404, 'Draft or source not found') from error
        if isinstance(error, PermissionError): raise HTTPException(403, str(error)) from error
        if isinstance(error, ValueError): raise HTTPException(422, str(error)) from error
        raise

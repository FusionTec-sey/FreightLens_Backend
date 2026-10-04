"""Permission-separated evidence selection and review; never financial posting."""
from uuid import UUID
from dataclasses import replace
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse, Response
from urllib.parse import quote
from sqlalchemy import or_, and_, func
from sqlalchemy.orm import Session, sessionmaker
from Model.db import get_db
from Model.containermgmt.Cinfo.Supplier import Supplier
from Model.containermgmt.Orders.OrderDocument import OrderDocument
from Model.containermgmt.Orders.PurchaseOrder import PurchaseOrder
from Model.containermgmt.Inventory.ManagerCase import ManagerCase
from Schema.CostChargeReviewSchema import CostChargeDeclaration
from Schema.CostEvidenceApiSchema import EvidenceRequest, SupplierChoice, DocumentChoice, EvidenceCaseRead
from Schema.ManagerCaseSchema import CaseActionRead, PolicyCaseReview
from Schema.InventoryLocationSchema import LocationPage
from Services.cost_charge_review_service import charge_review_binding, ACTION
from Services.cost_content_preparation_service import prepare_charge_content
from Services.inventory_posting_service import PostingConflict
from Services.manager_case_service import CaseBinding, request_case, review_case
from Services.manager_case_read_service import case_page, case_metadata
from Routes.Inventory.CostPoolRouter import cost_proposals, allocation_binding, allocation_review_error
from Utils.org_filter import apply_org_filter, apply_shared_or_org_filter, OrgContext
from auth.dependencies import get_org_context
from auth.module_guard import require_module
from auth.security_guards import require_permission, is_financial_user, can_view_supplier_user
from Utils.blob_storage import blob_storage
from Services.cost_runtime_service import server_cost_runtime, CostRuntimeUnavailable
from Services.cost_charge_review_service import reviewed_charge_binding
from Services.charge_posting_service import prepare_and_post_allocated_charge
from Model.containermgmt.Inventory.Valuation import InventoryValuation
from Schema.CostEvidenceApiSchema import ChargePostingRequest, ChargePostingContext, ChargePostingRead
from auth.policy import get_access_policy
from Model.Credentials.users import User
from Model.Credentials.Organisation import Organisation
from Services.staff_store_assignment_service import eligible_staff
from Services.evidence_config_service import (
    EvidenceConfigurationUnavailable, evidence_size_limit)
from Routes.MasterData.CustomerRouter import private_response


def posting_access(context, user):
    evidence_access(context, user)
    for permission in ('View_Financials', 'Manage_Financials', 'View_Product',
                       'View_Supplier', 'View_OrderDocument', 'Post_InventoryCost'):
        require_permission(permission)(user, context)


def current_posting_access(db, context, actor_id):
    if db.query(Organisation.id).filter_by(id=context.org_id, is_active=True).first() is None:
        raise PermissionError('Cost posting company is inactive')
    if eligible_staff(db, context).filter(User.id == actor_id).first() is None:
        raise PermissionError('Cost posting actor is unavailable in this company')
    actor = db.query(User).filter_by(id=actor_id, is_deleted=False).one()
    policy = get_access_policy(user=actor, org_context=context, db=db)
    if not policy.is_platform_admin and not {'INVENTORY', 'ORDERS'}.issubset(policy.module_names):
        raise PermissionError('Inventory and orders access required')
    posting_access(context, actor)


def evidence_access(context=Depends(get_org_context), user=Depends(require_permission('View_Financials'))):
    if not is_financial_user(user, context) or not can_view_supplier_user(user, context):
        raise HTTPException(403, 'Financial and supplier field access required')
    return user


CostEvidenceRouter = APIRouter(prefix='/inventory/cost-evidence', tags=['Inventory cost evidence'], dependencies=[
    Depends(require_module('INVENTORY')), Depends(require_module('ORDERS')),
    Depends(require_permission('View_Product')), Depends(require_permission('View_Supplier')),
    Depends(require_permission('View_OrderDocument')), Depends(evidence_access), Depends(private_response)])


@CostEvidenceRouter.get('/pools/{pool_id}/proposals/{key}/cases/{case_key}/posting-context', response_model=ChargePostingContext)
def posting_context(pool_id: int, key: UUID, case_key: UUID, db: Session = Depends(get_db),
                    context: OrgContext = Depends(get_org_context), user=Depends(require_permission('Post_InventoryCost'))):
    try:
        posting_access(context, user)
        if not db.in_transaction(): db.begin()
        server_cost_runtime().claim_for(db, context, pool_id)
        evidence_limit()
        binding = reviewed_charge_binding(db, context, case_key, key,
            authorize=lambda session: posting_access(context, user),
            load_allocation=lambda session: allocation_binding(session, context, pool_id, key),
            replay_operation_key=None, replay_actor_id=None)
        lines = binding.details['allocation']['details']['snapshot']['lines']
        products = sorted({line['product_id'] for line in lines})
        if not 1 <= len(products) <= 100: raise ValueError('Bounded allocation products required')
        # The existing org/pool/product/version unique index serves latest-stream reads.
        rows = apply_org_filter(db.query(InventoryValuation.product_id,
            func.max(InventoryValuation.version).label('version')).filter(
                InventoryValuation.org_id == context.org_id, InventoryValuation.cost_pool_id == pool_id,
                InventoryValuation.product_id.in_(products), InventoryValuation.is_deleted.is_(False)),
                InventoryValuation, context).group_by(InventoryValuation.product_id).order_by(InventoryValuation.product_id).all()
        if len(rows) != len(products): raise PostingConflict('Allocation valuation streams unavailable')
        return dict(case_key=case_key, proposal_key=key, pool_id=pool_id,
            streams=[dict(product_id=row.product_id, version=row.version) for row in rows])
    except CostRuntimeUnavailable as error:
        raise HTTPException(503, str(error)) from error
    except Exception as error:
        raise allocation_review_error(error) from error


@CostEvidenceRouter.post('/pools/{pool_id}/proposals/{key}/cases/{case_key}/post', response_model=ChargePostingRead)
def post_reviewed_charge(pool_id: int, key: UUID, case_key: UUID, payload: ChargePostingRequest,
                         db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
                         user=Depends(require_permission('Post_InventoryCost'))):
    try:
        posting_access(context, user)
        if not db.in_transaction(): db.begin()
        runtime = server_cost_runtime()
        claim = runtime.claim_for(db, context, pool_id)
        limit = evidence_limit()
        factory = sessionmaker(bind=db.get_bind())
        actor_id = user.id
        # No request-session transaction may span evidence object storage I/O.
        db.rollback()
        result = prepare_and_post_allocated_charge(factory, context, actor_id, payload.operation_key,
            proposal_key=key, case_key=case_key,
            expected_versions={row.product_id: row.version for row in payload.streams},
            authority_claim=claim, authorize=lambda session: current_posting_access(session, context, actor_id),
            require_central_authority=lambda session: runtime.claim_for(session, context, pool_id),
            load_allocation=lambda session: allocation_binding(session, context, pool_id, key),
            storage=blob_storage, max_bytes=limit)
        return dict(operation_key=result.operation_key, replayed=result.replayed, **result.result)
    except CostRuntimeUnavailable as error:
        db.rollback(); raise HTTPException(503, str(error)) from error
    except Exception as error:
        db.rollback(); raise allocation_review_error(error) from error


def document_choices(db, context):
    parent = db.query(PurchaseOrder.id).filter(PurchaseOrder.id == OrderDocument.po_id,
        PurchaseOrder.org_id == context.org_id, PurchaseOrder.is_deleted.is_(False)).correlate(OrderDocument).exists()
    return apply_org_filter(db.query(OrderDocument.id, OrderDocument.file_name.label('label'), OrderDocument.doc_type).filter(
        OrderDocument.org_id == context.org_id, OrderDocument.is_deleted.is_(False),
        OrderDocument.payment_id.is_(None), OrderDocument.vendor_quote_id.is_(None),
        or_(and_(OrderDocument.entity_type == 'GENERAL', OrderDocument.entity_id.is_(None)),
            and_(OrderDocument.entity_type == 'PO', OrderDocument.po_id.is_not(None),
                or_(OrderDocument.entity_id.is_(None), OrderDocument.entity_id == OrderDocument.po_id))),
        or_(OrderDocument.po_id.is_(None), parent)), OrderDocument, context)


def choices_page(query, page, limit):
    total = query.count()
    return dict(items=[dict(row._mapping) for row in query.offset((page-1)*limit).limit(limit).all()],
        page=page, limit=limit, total=total, pages=max(1, (total+limit-1)//limit))


@CostEvidenceRouter.get('/suppliers', response_model=LocationPage[SupplierChoice])
def suppliers(page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
        db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context)):
    query = apply_shared_or_org_filter(db.query(Supplier.supplier_id.label('id'), func.coalesce(Supplier.name, 'Unnamed supplier').label('label')).filter(
        Supplier.is_deleted.is_(False), Supplier.is_active.is_(True),
        or_(and_(Supplier.org_id == context.org_id, Supplier.is_shared.is_(False)),
            and_(Supplier.is_shared.is_(True), Supplier.org_id.is_(None)))), Supplier, context)
    return choices_page(query.order_by(Supplier.supplier_id), page, limit)


@CostEvidenceRouter.get('/documents', response_model=LocationPage[DocumentChoice])
def documents(page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
        db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context)):
    return choices_page(document_choices(db, context).order_by(OrderDocument.id), page, limit)


@CostEvidenceRouter.get('/documents/{document_id}/download')
def download_evidence(document_id: UUID, db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context)):
    # Reuse the existing storage adapter; no raw keys, public URLs or legacy fallback.
    eligible = document_choices(db, context).filter(OrderDocument.id == str(document_id)).with_for_update(read=True).first()
    if eligible is None:
        raise HTTPException(404, 'Evidence document not found')
    doc = db.get(OrderDocument, str(document_id))
    body, content_type, _ = blob_storage.get_file(doc.file_path)
    if body is None:
        raise HTTPException(404, 'Evidence file not found')
    return StreamingResponse(body, media_type=content_type or 'application/octet-stream', headers={
        'Content-Disposition': "attachment; filename*=UTF-8''" + quote(doc.file_name, safe=''),
        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})


def bound(db, context, pool_id, key, declaration, reviewer_id=None, document_content=None):
    ids = {str(value) for value in (declaration.document_id, declaration.fx_document_id) if value}
    if document_choices(db, context).filter(OrderDocument.id.in_(ids)).count() != len(ids):
        raise HTTPException(404, 'Select accessible general or purchase-order documents')
    result = charge_review_binding(db, context, key, declaration, authorize=lambda session: None,
        load_allocation=lambda session: allocation_binding(session, context, pool_id, key), reviewer_id=reviewer_id,
        document_content=document_content)
    if any(doc['entity_type'] not in ('GENERAL', 'PO') or doc['payment_id'] is not None or doc['vendor_quote_id'] is not None
           or (doc['entity_type'] == 'GENERAL' and doc['entity_id'] is not None)
           or (doc['entity_type'] == 'PO' and (doc['po_id'] is None or doc['entity_id'] not in (None, doc['po_id'])))
           for doc in result.details['documents']):
        raise HTTPException(404, 'Evidence document eligibility changed')
    return result


def scoped_cases(db, context, pool_id, key):
    if cost_proposals(db, context, pool_id).filter_by(proposal_key=key).first() is None:
        raise HTTPException(404, 'Allocation proposal not found')
    return apply_org_filter(db.query(ManagerCase).filter_by(org_id=context.org_id, is_deleted=False,
        action=ACTION, source_type='inventory.cost-allocation', source_key=str(key)), ManagerCase, context)


def evidence_limit():
    try:
        return evidence_size_limit()
    except EvidenceConfigurationUnavailable as error:
        raise HTTPException(503, str(error)) from error


def metadata_binding(binding):
    return replace(binding, source_version=1,
        details={name: value for name, value in binding.details.items() if name != 'document_content'})


def prepare_public(db, context, user, pool_id, key, declaration, case_key, *, reviewing=False):
    def source(session):
        current = bound(session, context, pool_id, key, declaration, user.id if reviewing else None)
        saved = scoped_cases(session, context, pool_id, key).filter_by(case_key=case_key).one_or_none()
        if saved is None:
            if reviewing: raise HTTPException(404, 'Charge evidence case not found')
            return current
        historical = CaseBinding(**saved.binding)
        if historical.source_version != 2:
            raise PostingConflict('Metadata-only cases require a new evidence request')
        if metadata_binding(historical).snapshot() != current.snapshot():
            raise PostingConflict('Evidence source changed')
        return historical
    try:
        prepared = prepare_charge_content(sessionmaker(bind=db.get_bind()),
            authorize=lambda session: evidence_access(context, user), load_binding=source,
            storage=blob_storage, max_bytes=evidence_limit())
    except (HTTPException, PermissionError, LookupError, ValueError, PostingConflict):
        raise
    except Exception as error:
        raise HTTPException(503, 'Versioned evidence storage is unavailable; no review was saved') from error
    def current(session):
        evidence_access(context, user)
        loaded = bound(session, context, pool_id, key, declaration, user.id if reviewing else None,
            document_content=prepared.content_map())
        if metadata_binding(loaded).snapshot() != metadata_binding(prepared.source).snapshot():
            raise PostingConflict('Evidence source changed during file preparation')
        if prepared.source.source_version == 2:
            prepared.require_current(loaded)
        return loaded
    return prepared, current


@CostEvidenceRouter.get('/pools/{pool_id}/proposals/{key}/cases/{case_key}/documents/{document_id}/download')
def download_reviewed_evidence(pool_id: int, key: UUID, case_key: UUID, document_id: UUID,
        db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context), user=Depends(evidence_access)):
    case = scoped_cases(db, context, pool_id, key).filter_by(case_key=case_key).one_or_none()
    if case is None: raise HTTPException(404, 'Charge evidence case not found')
    details = case.binding['details']
    content = details.get('document_content', {}).get(str(document_id))
    if case.source_version != 2 or content is None:
        raise HTTPException(409, 'No version-pinned document in this case; create a new evidence request')
    doc = next((item for item in details['documents'] if item['id'] == str(document_id)), None)
    if doc is None or document_choices(db, context).filter(OrderDocument.id == str(document_id)).first() is None:
        raise HTTPException(404, 'Evidence document unavailable')
    filename = doc['file_name']
    db.rollback()  # No database locks held during bounded object reads.
    try:
        body = blob_storage.read_verified_file_version(content, max_bytes=evidence_limit())
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(409, 'Reviewed file version is unavailable or changed') from error
    # Recheck company/document eligibility after I/O, without exposing a raw key.
    if document_choices(db, context).filter(OrderDocument.id == str(document_id)).first() is None:
        raise HTTPException(404, 'Evidence document unavailable')
    return Response(body, media_type='application/octet-stream', headers={
        'Content-Disposition': "attachment; filename*=UTF-8''" + quote(filename, safe=''),
        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})


@CostEvidenceRouter.post('/pools/{pool_id}/proposals/{key}/cases', response_model=CaseActionRead)
def request_evidence(pool_id: int, key: UUID, payload: EvidenceRequest, db: Session = Depends(get_db),
        context: OrgContext = Depends(get_org_context), user=Depends(require_permission('Manage_Financials'))):
    try:
        _, load = prepare_public(db, context, user, pool_id, key, payload.declaration, payload.operation_key)
        result = request_case(db, context, user.id, payload.operation_key, binding=load(db), reason=payload.reason,
            load_binding=load, authorize=lambda session: None)
        db.commit()
        return CaseActionRead(**result.result, replayed=result.replayed)
    except Exception as error:
        db.rollback(); raise allocation_review_error(error) from error


@CostEvidenceRouter.get('/pools/{pool_id}/proposals/{key}/cases', response_model=LocationPage[EvidenceCaseRead])
def list_evidence_cases(pool_id: int, key: UUID, page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
        view: Literal['ALL','NEEDS_MY_REVIEW','MY_REQUESTS'] = Query('ALL'), db: Session = Depends(get_db),
        context: OrgContext = Depends(get_org_context), user=Depends(evidence_access)):
    query = scoped_cases(db, context, pool_id, key)
    if view == 'NEEDS_MY_REVIEW':
        query = query.filter(ManagerCase.binding['details']['allocation']['details']['creator_id'].as_integer() != user.id)
    total, rows = case_page(db, query, user.id, view, page, limit)
    items = []
    for case, decision, used in rows:
        details = case.binding['details']; allocation = details['allocation']['details']
        items.append(dict(**case_metadata(case, decision, used), creator_id=allocation['creator_id'],
            charge_reference=details['declaration']['invoice_reference'], declaration_reason=details['declaration']['capitalisation_reason'],
            snapshot=allocation['snapshot'], declaration=details['declaration'], supplier_name=details['supplier']['name'] or 'Unnamed supplier',
            documents=[dict(id=doc['id'], label=doc['file_name'], doc_type=doc['doc_type']) for doc in details['documents']]))
    return dict(items=items, total=total, page=page, limit=limit, pages=max(1,(total+limit-1)//limit))


@CostEvidenceRouter.post('/pools/{pool_id}/proposals/{key}/cases/{case_key}/review', response_model=CaseActionRead)
def decide_evidence(pool_id: int, key: UUID, case_key: UUID, payload: PolicyCaseReview, db: Session = Depends(get_db),
        context: OrgContext = Depends(get_org_context), user=Depends(require_permission('Manage_Financials'))):
    try:
        case = scoped_cases(db, context, pool_id, key).filter_by(case_key=case_key).one_or_none()
        if case is None: raise HTTPException(404, 'Charge evidence case not found')
        declaration = CostChargeDeclaration(**case.binding['details']['declaration'])
        saved_binding = CaseBinding(**case.binding)
        if saved_binding.source_version == 2:
            # Release the read-only lookup transaction before storage preparation.
            db.rollback()
            _, load = prepare_public(db, context, user, pool_id, key, declaration, case_key, reviewing=True)
        else:
            load = lambda session: bound(session, context, pool_id, key, declaration, user.id)
        if not db.in_transaction():
            db.begin()
        result = review_case(db, context, user.id, payload.operation_key, case_key=case_key, binding=saved_binding,
            expected_version=payload.expected_version, outcome=payload.outcome, reason=payload.reason,
            load_binding=load, authorize=lambda session: None)
        db.commit()
        return CaseActionRead(**result.result, replayed=result.replayed)
    except Exception as error:
        db.rollback(); raise allocation_review_error(error) from error

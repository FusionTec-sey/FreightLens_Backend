"""Permission-scoped receipt review and approved atomic stock/value posting."""
from uuid import UUID
from typing import Literal
from fastapi import APIRouter, Depends, Query, HTTPException, Response
from sqlalchemy.orm import Session, sessionmaker
from urllib.parse import quote
from Model.db import get_db
from Model.containermgmt.Inventory.ReceiptManifest import InventoryReceiptManifestRecord as Manifest
from Model.containermgmt.Inventory.ManagerCase import ManagerCase, ManagerCaseDecision, ManagerCaseUse
from Model.containermgmt.Inventory.CostPool import BranchCostPool, InventoryCostPool
from Model.containermgmt.Inventory.Valuation import InventoryValuation
from Model.containermgmt.Orders.GoodsReceipt import GoodsReceipt, ReceiptItem
from Model.containermgmt.Orders.PurchaseOrder import PurchaseOrder
from Model.Credentials.Organisation import Organisation
from Model.Credentials.users import User
from Schema.InventoryReceiptSchema import (InventoryReceiptManifest, ReceiptManifestCreate,
    ReceiptManifestSaved, ReceiptManifestPreview, ReceiptManifestSummary, ReceiptManifestDetail,
    ReceiptManifestReviewCase, InventoryReceiptSource, ReceiptSourceSnapshot,
    ReceiptPostingContext, ReceiptPostingRead, ReceiptPostingRequest)
from Schema.InventoryLocationSchema import LocationPage
from Schema.StockReclassificationSchema import ReclassificationReviewRequest
from Schema.ManagerCaseSchema import PolicyCaseReview, CaseActionRead
from Schema.ReceiptCostReviewSchema import (
    ReceiptCostCaseRead, ReceiptCostDeclaration, ReceiptCostReviewRequest)
from Schema.DocumentContentSchema import DocumentContentFingerprint
from Services.inventory_receipt_manifest_store import save_receipt_manifest
from Services.inventory_receipt_manifest_service import prepare_inventory_receipt_manifest
from Services.inventory_receipt_source_service import prepare_inventory_receipt_source
from Services.inventory_receipt_review_service import request_receipt_review, review_receipt_manifest
from Services.inventory_receipt_cost_review_service import (
    ACTION as RECEIPT_COST_ACTION, metadata_binding,
    receipt_cost_binding, request_receipt_cost_review, review_receipt_cost)
from Services.inventory_receipt_cost_content_service import prepare_receipt_cost_content
from Services.inventory_receipt_posting_service import prepare_and_post_reviewed_receipt
from Services.inventory_posting_service import PostingConflict
from Services.manager_case_service import CaseBinding
from Services.manager_case_read_service import case_metadata, case_page
from Services.evidence_config_service import (
    EvidenceConfigurationUnavailable, evidence_size_limit)
from Services.stock_runtime_service import StockRuntimeUnavailable, server_stock_runtime
from Services.cost_runtime_service import CostRuntimeUnavailable, server_cost_runtime
from Services.staff_store_assignment_service import eligible_staff
from Utils.org_filter import OrgContext, apply_org_filter
from Utils.blob_storage import blob_storage
from auth.dependencies import get_org_context, get_current_user
from auth.security_guards import (
    require_permission, has_permission, is_financial_user, can_view_supplier_user)
from auth.module_guard import require_module
from auth.policy import get_access_policy


def private_response(response: Response):
    response.headers['Cache-Control'] = 'no-store'


ReceiptManifestRouter = APIRouter(prefix='/inventory/receipt-manifests', tags=['Inventory receipt manifests'],
    dependencies=[Depends(require_module('INVENTORY')), Depends(require_module('ORDERS')),
        Depends(require_permission('View_Product')), Depends(require_permission('View_GoodsReceipt')),
        Depends(private_response)])


def scoped(db, context):
    if context.org_id not in context.allowed_org_ids:
        raise HTTPException(403, 'Select an allowed company')
    return apply_org_filter(db.query(Manifest).join(GoodsReceipt,
        (GoodsReceipt.id == Manifest.receipt_id) & (GoodsReceipt.org_id == Manifest.org_id))
        .join(ReceiptItem, (ReceiptItem.id == Manifest.receipt_item_id) & (ReceiptItem.receipt_id == GoodsReceipt.id))
        .join(PurchaseOrder, (PurchaseOrder.id == GoodsReceipt.po_id) & (PurchaseOrder.org_id == Manifest.org_id))
        .filter(Manifest.org_id == context.org_id, Manifest.is_deleted.is_(False),
            GoodsReceipt.is_deleted.is_(False), ReceiptItem.is_deleted.is_(False), PurchaseOrder.is_deleted.is_(False)), Manifest, context)


def summary(row, source):
    return dict(manifest_key=row.manifest_key, receipt_id=row.receipt_id,
        receipt_item_id=row.receipt_item_id, product_id=source['product_id'],
        branch_id=source['branch_id'], location_id=source['location_id'],
        created_at=row.created_at, created_by=row.created_by)


def translate(error):
    if isinstance(error, HTTPException): return error
    if isinstance(error, LookupError): return HTTPException(404, str(error))
    if isinstance(error, PostingConflict): return HTTPException(409, str(error))
    if isinstance(error, PermissionError): return HTTPException(403, str(error))
    if isinstance(error, ValueError): return HTTPException(422, str(error))
    return error


def visible_manifest(db, context, key):
    row = scoped(db, context).filter(Manifest.manifest_key == key).one_or_none()
    if row is None: raise HTTPException(404, 'Receipt manifest not found')
    return row


def receipt_cases(db, context, key):
    visible_manifest(db, context, key)
    return apply_org_filter(db.query(ManagerCase).filter(ManagerCase.org_id == context.org_id,
        ManagerCase.is_deleted.is_(False), ManagerCase.action == 'inventory.receipt.classify',
        ManagerCase.source_type == 'inventory.receipt.manifest', ManagerCase.source_key == str(key)),
        ManagerCase, context)


def receipt_cost_cases(db, context, key):
    visible_manifest(db, context, key)
    return apply_org_filter(db.query(ManagerCase).filter(
        ManagerCase.org_id == context.org_id, ManagerCase.is_deleted.is_(False),
        ManagerCase.action == RECEIPT_COST_ACTION,
        ManagerCase.source_type == 'inventory.receipt.manifest',
        ManagerCase.source_key == str(key)), ManagerCase, context)


def receipt_cost_access(context, user, permission=None):
    required = {'View_Financials', 'View_Supplier', 'View_OrderDocument'}
    if permission:
        required.add(permission)
    if (not all(has_permission(user, name) for name in required)
            or not is_financial_user(user, context)
            or not can_view_supplier_user(user, context)):
        raise HTTPException(403, 'Financial and supplier evidence access required')
    return user


def receipt_posting_access(context, user):
    required = {
        'View_Product', 'View_GoodsReceipt', 'Verify_Receipt',
        'Post_InventoryReceipt', 'View_Financials', 'Manage_Financials',
        'View_Supplier', 'View_OrderDocument', 'Post_InventoryCost',
    }
    if (not all(has_permission(user, name) for name in required)
            or not is_financial_user(user, context)
            or not can_view_supplier_user(user, context)):
        raise PermissionError(
            'Receipt posting requires separate stock, cost and evidence authority')
    return user


def current_receipt_actor(db, context, actor_id):
    if db.query(Organisation.id).filter_by(
            id=context.org_id, is_active=True).first() is None:
        raise PermissionError('Receipt posting company is inactive')
    if eligible_staff(db, context).filter(User.id == actor_id).first() is None:
        raise PermissionError('Receipt posting actor is unavailable in this company')
    actor = db.query(User).filter_by(id=actor_id, is_deleted=False).one_or_none()
    if actor is None:
        raise PermissionError('Receipt posting actor is unavailable')
    actor.access_policy = get_access_policy(user=actor, org_context=context, db=db)
    if (not actor.access_policy.is_platform_admin
            and not {'INVENTORY', 'ORDERS'}.issubset(
                actor.access_policy.module_names)):
        raise PermissionError('Inventory and orders access required')
    receipt_posting_access(context, actor)
    return actor


def receipt_posting_scope(db, context, key):
    record = visible_manifest(db, context, key)
    try:
        branch_id = record.snapshot['source']['branch_id']
        product_id = record.snapshot['source']['product_id']
    except (KeyError, TypeError):
        raise PostingConflict('Receipt manifest has an invalid posting scope') from None
    if any(type(value) is not int or value <= 0
            for value in (branch_id, product_id)):
        raise PostingConflict('Receipt manifest has an invalid posting scope')
    mapping = apply_org_filter(db.query(BranchCostPool).join(
        InventoryCostPool,
        (InventoryCostPool.id == BranchCostPool.cost_pool_id)
        & (InventoryCostPool.org_id == BranchCostPool.org_id)).filter(
            BranchCostPool.org_id == context.org_id,
            BranchCostPool.branch_id == branch_id,
            BranchCostPool.is_deleted.is_(False),
            InventoryCostPool.is_active.is_(True),
            InventoryCostPool.is_deleted.is_(False)),
        BranchCostPool, context).one_or_none()
    if mapping is None:
        raise ValueError('An active exact branch cost-pool mapping is required')
    latest = apply_org_filter(db.query(InventoryValuation.version).filter(
        InventoryValuation.org_id == context.org_id,
        InventoryValuation.cost_pool_id == mapping.cost_pool_id,
        InventoryValuation.product_id == product_id,
        InventoryValuation.is_deleted.is_(False)),
        InventoryValuation, context).order_by(
            InventoryValuation.version.desc()).first()
    return dict(manifest_key=key, branch_id=branch_id,
        product_id=product_id, cost_pool_id=mapping.cost_pool_id,
        valuation_version=latest.version if latest else 0)


def receipt_cost_case_access(context=Depends(get_org_context),
        user=Depends(get_current_user)):
    if not (has_permission(user, 'Request_ReceiptCostReview')
            or has_permission(user, 'Review_ReceiptCostReview')):
        raise HTTPException(403, 'Receipt cost-review access required')
    return receipt_cost_access(context, user)


def prepare_public_receipt_cost(db, context, user, key, declaration, case_key,
                                *, reviewing=False):
    permission = 'Review_ReceiptCostReview' if reviewing \
        else 'Request_ReceiptCostReview'

    def authorize(session):
        receipt_cost_access(context, user, permission)

    def source(session):
        current = receipt_cost_binding(session, context, key, declaration,
            authorize=authorize, reviewer_id=user.id if reviewing else None)
        saved = receipt_cost_cases(session, context, key).filter(
            ManagerCase.case_key == case_key).one_or_none()
        if saved is None:
            if reviewing:
                raise LookupError('Receipt cost-review case not found')
            return current
        historical = CaseBinding(**saved.binding)
        if historical.source_version != 2:
            raise PostingConflict(
                'Metadata-only receipt cost cases require a new evidence request')
        if metadata_binding(historical).snapshot() != current.snapshot():
            raise PostingConflict('Receipt cost evidence source changed')
        return historical

    try:
        prepared = prepare_receipt_cost_content(sessionmaker(bind=db.get_bind()),
            authorize=authorize, load_binding=source, storage=blob_storage,
            max_bytes=evidence_size_limit())
    except EvidenceConfigurationUnavailable as error:
        raise HTTPException(503, str(error)) from error
    except (HTTPException, PermissionError, LookupError, ValueError, PostingConflict):
        raise
    except Exception as error:
        raise HTTPException(503,
            'Versioned evidence storage is unavailable; no receipt cost review was saved') from error

    def current(session):
        authorize(session)
        loaded = receipt_cost_binding(session, context, key, declaration,
            authorize=authorize, reviewer_id=user.id if reviewing else None,
            document_content=prepared.content_map())
        if metadata_binding(loaded).snapshot() != \
                metadata_binding(prepared.source).snapshot():
            raise PostingConflict('Receipt cost evidence changed during file preparation')
        if prepared.source.source_version == 2:
            prepared.require_current(loaded)
        return loaded

    return prepared, current


def receipt_case_access(user=Depends(get_current_user)):
    if not (has_permission(user, 'Request_InventoryReview') or has_permission(user, 'Review_InventoryPolicy')):
        raise HTTPException(403, 'Receipt classification review access required')
    return user


@ReceiptManifestRouter.post('/source-preview', response_model=ReceiptSourceSnapshot)
def preview_receipt_source(payload: InventoryReceiptSource, db: Session = Depends(get_db),
        context: OrgContext = Depends(get_org_context), user=Depends(require_permission('Verify_Receipt'))):
    """Resolve exact base quantities before the operator classifies conditions."""
    try:
        if not db.in_transaction(): db.begin()
        result = prepare_inventory_receipt_source(db, context, payload, authorize=lambda session: None)
        db.rollback()
        return result
    except Exception as error:
        db.rollback(); raise translate(error) from error


@ReceiptManifestRouter.post('/preview', response_model=ReceiptManifestPreview)
def preview_manifest(payload: InventoryReceiptManifest, db: Session = Depends(get_db),
        context: OrgContext = Depends(get_org_context), user=Depends(require_permission('Verify_Receipt'))):
    """Validate and convert one classification without saving or posting it."""
    try:
        if not db.in_transaction(): db.begin()
        result = prepare_inventory_receipt_manifest(db, context, payload, authorize=lambda session: None)
        # Release source locks immediately. Validation must never become a long-lived
        # transaction or imply that the later save can skip authoritative rechecks.
        db.rollback()
        return result
    except Exception as error:
        db.rollback(); raise translate(error) from error


@ReceiptManifestRouter.post('', response_model=ReceiptManifestSaved)
def create_manifest(payload: ReceiptManifestCreate, db: Session = Depends(get_db),
        context: OrgContext = Depends(get_org_context), user=Depends(require_permission('Verify_Receipt'))):
    try:
        if not db.in_transaction(): db.begin()
        manifest = InventoryReceiptManifest.model_validate(payload.model_dump(exclude={'operation_key'}))
        outcome = save_receipt_manifest(db, context, user.id, payload.operation_key, manifest,
            authorize=lambda session: None)
        db.commit()
        return ReceiptManifestSaved(**outcome.result, replayed=outcome.replayed)
    except Exception as error:
        db.rollback(); raise translate(error) from error


@ReceiptManifestRouter.post('/{key}/request-review', response_model=CaseActionRead)
def request_manifest_review(key: UUID, payload: ReclassificationReviewRequest,
        db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
        user=Depends(require_permission('Request_InventoryReview'))):
    try:
        if not db.in_transaction(): db.begin()
        outcome = request_receipt_review(db, context, user.id, payload.operation_key,
            manifest_key=key, reason=payload.reason, authorize=lambda session: None)
        db.commit()
        return CaseActionRead(**outcome.result, replayed=outcome.replayed)
    except Exception as error:
        db.rollback(); raise translate(error) from error


@ReceiptManifestRouter.get('/{key}/cases', response_model=LocationPage[ReceiptManifestReviewCase])
def list_manifest_reviews(key: UUID, page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
        view: Literal['ALL', 'NEEDS_MY_REVIEW', 'MY_REQUESTS'] = Query('ALL'),
        db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
        user=Depends(receipt_case_access)):
    can_review = has_permission(user, 'Review_InventoryPolicy')
    if view != 'MY_REQUESTS' and not can_review:
        raise HTTPException(403, 'Review permission is required for this case view')
    manifest = visible_manifest(db, context, key)
    query = receipt_cases(db, context, key)
    decided = db.query(ManagerCaseDecision.id).filter(ManagerCaseDecision.org_id == ManagerCase.org_id,
        ManagerCaseDecision.case_id == ManagerCase.id).correlate(ManagerCase).exists()
    used = db.query(ManagerCaseUse.id).filter(ManagerCaseUse.org_id == ManagerCase.org_id,
        ManagerCaseUse.case_id == ManagerCase.id).correlate(ManagerCase).exists()
    if view == 'NEEDS_MY_REVIEW': query = query.filter(ManagerCase.created_by != user.id, ~decided, ~used)
    elif view == 'MY_REQUESTS': query = query.filter(ManagerCase.created_by == user.id)
    total = query.count()
    rows = query.outerjoin(ManagerCaseDecision, (ManagerCaseDecision.case_id == ManagerCase.id) &
        (ManagerCaseDecision.org_id == ManagerCase.org_id)).outerjoin(ManagerCaseUse,
        (ManagerCaseUse.case_id == ManagerCase.id) & (ManagerCaseUse.org_id == ManagerCase.org_id)
        ).with_entities(ManagerCase.case_key, ManagerCase.created_at, ManagerCase.created_by,
            ManagerCase.reason, ManagerCaseDecision.id.label('decision_id'),
            ManagerCaseDecision.outcome, ManagerCaseDecision.created_by.label('reviewer_id'),
            ManagerCaseDecision.reason.label('review_reason'), ManagerCaseUse.id.label('use_id')
        ).order_by(ManagerCase.id.desc()).offset((page - 1) * limit).limit(limit).all()
    source = manifest.snapshot['source']
    items = [ReceiptManifestReviewCase(case_key=row.case_key, manifest_key=key,
        version=3 if row.use_id else 2 if row.decision_id else 1,
        status='CONSUMED' if row.use_id else row.outcome if row.decision_id else 'REQUESTED',
        receipt_id=source['receipt_id'], receipt_item_id=source['receipt_item_id'],
        product_id=source['product_id'], branch_id=source['branch_id'], location_id=source['location_id'],
        reason=row.reason, requestor_id=row.created_by, reviewer_id=row.reviewer_id,
        review_reason=row.review_reason, requested_at=row.created_at) for row in rows]
    return dict(items=items, total=total, page=page, limit=limit,
        pages=max(1, (total + limit - 1) // limit))


@ReceiptManifestRouter.post('/{key}/cases/{case_key}/review', response_model=CaseActionRead)
def review_manifest(key: UUID, case_key: UUID, payload: PolicyCaseReview,
        db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
        user=Depends(require_permission('Review_InventoryPolicy'))):
    try:
        if not db.in_transaction(): db.begin()
        case = receipt_cases(db, context, key).filter(ManagerCase.case_key == case_key).one_or_none()
        if case is None: raise HTTPException(404, 'Receipt classification review not found')
        outcome = review_receipt_manifest(db, context, user.id, payload.operation_key,
            manifest_key=key, case_key=case_key, expected_version=payload.expected_version,
            outcome=payload.outcome, reason=payload.reason, authorize=lambda session: None)
        db.commit()
        return CaseActionRead(**outcome.result, replayed=outcome.replayed)
    except Exception as error:
        db.rollback(); raise translate(error) from error


@ReceiptManifestRouter.post('/{key}/cost-cases', response_model=CaseActionRead)
def request_cost_review(key: UUID, payload: ReceiptCostReviewRequest,
        db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
        user=Depends(require_permission('Request_ReceiptCostReview'))):
    """Capture exact versioned PO-price/FX evidence; never post stock or value."""
    try:
        receipt_cost_access(context, user, 'Request_ReceiptCostReview')
        prepared, current = prepare_public_receipt_cost(db, context, user, key,
            payload.declaration, payload.operation_key)
        if not db.in_transaction():
            db.begin()
        current(db)
        outcome = request_receipt_cost_review(db, context, user.id,
            payload.operation_key, manifest_key=key,
            declaration=payload.declaration, reason=payload.reason,
            authorize=lambda session: receipt_cost_access(
                context, user, 'Request_ReceiptCostReview'),
            document_content=prepared.content_map())
        db.commit()
        return CaseActionRead(**outcome.result, replayed=outcome.replayed)
    except Exception as error:
        db.rollback(); raise translate(error) from error


@ReceiptManifestRouter.get('/{key}/cost-cases',
    response_model=LocationPage[ReceiptCostCaseRead])
def list_cost_reviews(key: UUID, page: int = Query(1, ge=1),
        limit: int = Query(25, ge=1, le=100),
        view: Literal['ALL', 'NEEDS_MY_REVIEW', 'MY_REQUESTS'] = Query('ALL'),
        db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
        user=Depends(receipt_cost_case_access)):
    can_review = has_permission(user, 'Review_ReceiptCostReview')
    if view != 'MY_REQUESTS' and not can_review:
        raise HTTPException(403, 'Receipt cost review permission is required for this view')
    query = receipt_cost_cases(db, context, key)
    total, rows = case_page(db, query, user.id, view, page, limit)
    items = []
    for case, decision, used in rows:
        details = case.binding['details']
        documents = [dict(id=doc['id'], label=doc['file_name'],
            doc_type=doc['doc_type']) for doc in details['documents']]
        items.append(ReceiptCostCaseRead(
            **case_metadata(case, decision, used), manifest_key=key,
            declaration=details['declaration'],
            receipt_quantity=details['receipt_quantity'],
            goods_value_source=details['goods_value_source'],
            goods_value_scr=details['goods_value_scr'], documents=documents))
    return dict(items=items, total=total, page=page, limit=limit,
        pages=max(1, (total + limit - 1) // limit))


@ReceiptManifestRouter.post('/{key}/cost-cases/{case_key}/review',
    response_model=CaseActionRead)
def decide_cost_review(key: UUID, case_key: UUID, payload: PolicyCaseReview,
        db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
        user=Depends(require_permission('Review_ReceiptCostReview'))):
    try:
        receipt_cost_access(context, user, 'Review_ReceiptCostReview')
        factory = sessionmaker(bind=db.get_bind())
        with factory() as source_db:
            case = receipt_cost_cases(source_db, context, key).filter(
                ManagerCase.case_key == case_key).one_or_none()
            if case is None:
                raise LookupError('Receipt cost-review case not found')
            declaration = ReceiptCostDeclaration(
                **case.binding['details']['declaration'])
        _, current = prepare_public_receipt_cost(db, context, user, key,
            declaration, case_key, reviewing=True)
        if not db.in_transaction():
            db.begin()
        current(db)
        outcome = review_receipt_cost(db, context, user.id,
            payload.operation_key, manifest_key=key, case_key=case_key,
            expected_version=payload.expected_version, outcome=payload.outcome,
            reason=payload.reason,
            authorize=lambda session: receipt_cost_access(
                context, user, 'Review_ReceiptCostReview'))
        db.commit()
        return CaseActionRead(**outcome.result, replayed=outcome.replayed)
    except Exception as error:
        db.rollback(); raise translate(error) from error


@ReceiptManifestRouter.get('/{key}/cost-cases/{case_key}/documents/{document_id}')
def download_cost_review_document(key: UUID, case_key: UUID, document_id: UUID,
        db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context),
        user=Depends(receipt_cost_case_access)):
    try:
        factory = sessionmaker(bind=db.get_bind())

        def load(source_db):
            case = receipt_cost_cases(source_db, context, key).filter(
                ManagerCase.case_key == case_key).one_or_none()
            if case is None or case.source_version != 2:
                raise LookupError('Receipt cost-review case not found')
            saved = CaseBinding(**case.binding)
            details = saved.details
            content = details.get('document_content', {}).get(str(document_id))
            document = next((row for row in details['documents']
                if row['id'] == str(document_id)), None)
            if content is None or document is None:
                raise LookupError('Reviewed receipt cost document not found')
            declaration = ReceiptCostDeclaration(**details['declaration'])
            fingerprints = {name: DocumentContentFingerprint(**value)
                for name, value in details['document_content'].items()}
            current = receipt_cost_binding(source_db, context, key, declaration,
                authorize=lambda session: receipt_cost_access(context, user),
                document_content=fingerprints)
            if current.snapshot() != saved.snapshot():
                raise PostingConflict('Reviewed receipt cost evidence changed')
            return saved, content, document['file_name']

        with factory.begin() as source_db:
            saved, content, filename = load(source_db)
        body = blob_storage.read_verified_file_version(content,
            max_bytes=evidence_size_limit())
        with factory.begin() as source_db:
            current, _, _ = load(source_db)
            if current.snapshot() != saved.snapshot():
                raise PostingConflict('Reviewed receipt cost evidence changed')
        return Response(body, media_type='application/octet-stream', headers={
            'Content-Disposition': "attachment; filename*=UTF-8''" +
                quote(filename, safe=''),
            'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})
    except EvidenceConfigurationUnavailable as error:
        db.rollback(); raise HTTPException(503, str(error)) from error
    except Exception as error:
        db.rollback(); raise translate(error) from error


@ReceiptManifestRouter.get('/{key}/posting-context',
    response_model=ReceiptPostingContext)
def posting_context(key: UUID, db: Session = Depends(get_db),
        context: OrgContext = Depends(get_org_context),
        user=Depends(require_permission('Post_InventoryReceipt'))):
    """Return only server-derived branch/pool/version context; never post."""
    try:
        receipt_posting_access(context, user)
        if not db.in_transaction():
            db.begin()
        scope = receipt_posting_scope(db, context, key)
        server_stock_runtime().claim_for(
            db, context, scope['branch_id'])
        server_cost_runtime().claim_for(
            db, context, scope['cost_pool_id'])
        evidence_size_limit()
        return scope
    except (StockRuntimeUnavailable, CostRuntimeUnavailable,
            EvidenceConfigurationUnavailable) as error:
        db.rollback(); raise HTTPException(503, str(error)) from error
    except Exception as error:
        db.rollback(); raise translate(error) from error


@ReceiptManifestRouter.post('/{key}/post', response_model=ReceiptPostingRead)
def post_approved_receipt(key: UUID, payload: ReceiptPostingRequest,
        db: Session = Depends(get_db),
        context: OrgContext = Depends(get_org_context),
        user=Depends(require_permission('Post_InventoryReceipt'))):
    """Atomically consume both approvals and post physical/value history."""
    try:
        receipt_posting_access(context, user)
        if not db.in_transaction():
            db.begin()
        scope = receipt_posting_scope(db, context, key)
        stock_runtime = server_stock_runtime()
        cost_runtime = server_cost_runtime()
        stock_claim = stock_runtime.claim_for(
            db, context, scope['branch_id'])
        cost_claim = cost_runtime.claim_for(
            db, context, scope['cost_pool_id'])
        limit = evidence_size_limit()
        factory = sessionmaker(bind=db.get_bind())
        actor_id = user.id
        db.rollback()

        def authorize_stock(session):
            current_receipt_actor(session, context, actor_id)
            if stock_runtime.claim_for(
                    session, context, scope['branch_id']) != stock_claim:
                raise PermissionError('Receiving-store authority changed')

        def authorize_cost(session):
            current_receipt_actor(session, context, actor_id)
            if cost_runtime.claim_for(
                    session, context, scope['cost_pool_id']) != cost_claim:
                raise PermissionError('Central cost authority changed')

        result = prepare_and_post_reviewed_receipt(
            factory, context, actor_id, payload.operation_key,
            manifest_key=key,
            classification_case_key=payload.classification_case_key,
            cost_case_key=payload.cost_case_key,
            expected_valuation_version=payload.expected_valuation_version,
            reason=payload.reason,
            stock_authority=stock_claim, cost_authority=cost_claim,
            authorize_stock=authorize_stock, authorize_cost=authorize_cost,
            storage=blob_storage, max_bytes=limit)
        return ReceiptPostingRead(operation_key=result.operation_key,
            replayed=result.replayed, **result.result)
    except (StockRuntimeUnavailable, CostRuntimeUnavailable,
            EvidenceConfigurationUnavailable) as error:
        db.rollback(); raise HTTPException(503, str(error)) from error
    except Exception as error:
        db.rollback(); raise translate(error) from error


@ReceiptManifestRouter.get('', response_model=LocationPage[ReceiptManifestSummary])
def list_manifests(page: int = Query(1, ge=1), limit: int = Query(25, ge=1, le=100),
        receipt_id: int | None = Query(None, gt=0), db: Session = Depends(get_db),
        context: OrgContext = Depends(get_org_context)):
    query = scoped(db, context)
    if receipt_id is not None: query = query.filter(Manifest.receipt_id == receipt_id)
    total = query.count()
    # Do not read potentially 1000 serial/batch entries for every register row.
    rows = query.with_entities(Manifest.manifest_key, Manifest.receipt_id, Manifest.receipt_item_id,
        Manifest.created_at, Manifest.created_by, Manifest.snapshot['source'].label('source')).order_by(
        Manifest.created_at.desc(), Manifest.manifest_key).offset((page - 1) * limit).limit(limit).all()
    return dict(items=[summary(row, row.source) for row in rows], total=total,
        page=page, limit=limit, pages=max(1, (total + limit - 1) // limit))


@ReceiptManifestRouter.get('/{key}', response_model=ReceiptManifestDetail)
def read_manifest(key: UUID, db: Session = Depends(get_db), context: OrgContext = Depends(get_org_context)):
    row = visible_manifest(db, context, key)
    return dict(**summary(row, row.snapshot['source']),
        source=row.snapshot['source'], manifest=row.snapshot['manifest'],
        quantities=row.snapshot['quantities'], condition_review_required=row.snapshot['condition_review_required'])

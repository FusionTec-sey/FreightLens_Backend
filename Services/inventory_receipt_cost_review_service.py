"""Versionable receipt PO-price and FX evidence through shared manager cases."""
from dataclasses import replace
from decimal import Decimal
from uuid import UUID
from Model.containermgmt.Inventory.ManagerCase import (
    ManagerCase, ManagerCaseDecision, ManagerCaseUse)
from Model.containermgmt.Inventory.PostingOperation import PostingOperation
from Model.containermgmt.Orders.OrderDocument import OrderDocument
from Model.containermgmt.Orders.PurchaseOrder import PurchaseOrder
from Model.containermgmt.Orders.POItem import POItem
from Schema.DocumentContentSchema import DocumentContentFingerprint
from Schema.ReceiptCostReviewSchema import ReceiptCostDeclaration
from Services.inventory_receipt_review_service import receipt_manifest_binding
from Services.inventory_posting_service import PostingConflict
from Services.manager_case_service import CaseBinding, request_case, review_case
from Utils.org_filter import apply_org_filter


ACTION = 'inventory.receipt.verify-cost'
RECEIPT_POSTING_KIND = 'inventory.receipt.post.v1'


def _owned(db, model, context):
    return apply_org_filter(db.query(model).filter(
        model.org_id == context.org_id, model.is_deleted.is_(False)), model, context)


def metadata_binding(binding):
    return replace(binding, source_version=1,
        details={name: value for name, value in binding.details.items()
                 if name != 'document_content'})


def receipt_cost_binding(db, context, manifest_key, declaration, *, authorize,
                         reviewer_id=None, document_content=None):
    if not db.in_transaction():
        raise ValueError('Receipt cost review requires an active transaction')
    if not callable(authorize):
        raise ValueError('Receipt cost permission guard required')
    if not isinstance(manifest_key, UUID) or not manifest_key.int:
        raise ValueError('Nonzero receipt manifest identity required')
    if not isinstance(declaration, ReceiptCostDeclaration):
        raise ValueError('Typed receipt cost declaration required')
    declaration = ReceiptCostDeclaration.model_validate(
        declaration.model_dump(mode='json'))
    manifest = receipt_manifest_binding(db, context, manifest_key,
        authorize=authorize)
    source = manifest.details['snapshot']['source']
    item = _owned(db, POItem, context).filter_by(id=source['po_item_id'],
        po_id=source['po_id'], item_status='ACTIVE').populate_existing().with_for_update(
            of=POItem).one_or_none()
    order = _owned(db, PurchaseOrder, context).filter_by(id=source['po_id'],
        doc_type='PO').populate_existing().with_for_update(of=PurchaseOrder).one_or_none()
    if item is None or order is None or item.product_id != source['product_id']:
        raise PostingConflict('Receipt purchasing cost source changed')
    if item.po_unit_price is None or item.po_unit_price <= 0:
        raise PostingConflict('Receipt requires an explicit official PO unit price')
    source_currency = (item.currency or order.currency or '').strip().upper()
    if (not source_currency or source_currency != declaration.source_currency
            or ((order.currency or '').strip().upper() not in ('', source_currency))):
        raise PostingConflict('Receipt source currency differs from the official PO')
    if format(item.po_unit_price, '.6f') != declaration.unit_price_source:
        raise PostingConflict('Receipt unit price differs from the official PO')
    source_value, scr_value = declaration.values(Decimal(source['received_quantity']))
    ids = sorted({str(value) for value in
        (declaration.document_id, declaration.fx_document_id) if value})
    columns = ('id', 'entity_type', 'entity_id', 'po_id', 'payment_id',
        'vendor_quote_id', 'doc_type', 'title', 'file_name', 'file_path',
        'file_size', 'mime_type', 'is_confidential', 'updated_at')
    docs = _owned(db, OrderDocument, context).filter(
        OrderDocument.id.in_(ids)).with_entities(
            *(getattr(OrderDocument, name) for name in columns)).order_by(
                OrderDocument.id).with_for_update(read=True).all()
    if len(docs) != len(ids):
        raise PermissionError('Receipt cost documents unavailable in this company')
    price = next((doc for doc in docs
        if str(doc.id) == str(declaration.document_id)), None)
    if (price is None or price.entity_type != 'PO' or price.po_id != order.id
            or price.entity_id not in (None, order.id)
            or price.payment_id is not None or price.vendor_quote_id is not None):
        raise PostingConflict('Receipt price evidence must belong to the exact purchase order')
    for doc in docs:
        if (doc.payment_id is not None or doc.vendor_quote_id is not None
                or doc.entity_type not in ('GENERAL', 'PO')
                or (doc.entity_type == 'PO' and
                    (doc.po_id != order.id or doc.entity_id not in (None, order.id)))
                or (doc.entity_type == 'GENERAL' and doc.entity_id is not None)):
            raise PostingConflict('Receipt cost evidence has an unsupported document scope')
    documents = []
    for doc in docs:
        snapshot = dict(doc._mapping)
        snapshot['updated_at'] = snapshot['updated_at'].isoformat() \
            if snapshot['updated_at'] else None
        documents.append(snapshot)
    details = dict(receipt=manifest.snapshot(),
        declaration=declaration.model_dump(mode='json'),
        calculation_policy='receipt-po-fx-v1',
        receipt_quantity=source['received_quantity'],
        goods_value_source=source_value, goods_value_scr=scr_value,
        documents=documents, manifest_created_by=manifest.details['manifest_created_by'])
    if reviewer_id == manifest.details['manifest_created_by']:
        raise PermissionError('Receipt manifest creators cannot verify its cost evidence')
    version = 1
    if document_content is not None:
        if not isinstance(document_content, dict) or set(document_content) != set(ids):
            raise PostingConflict('Content evidence must cover exactly the receipt documents')
        content = {}
        for doc in documents:
            fingerprint = document_content[doc['id']]
            if not isinstance(fingerprint, DocumentContentFingerprint):
                raise ValueError('Typed server-prepared content fingerprint required')
            fingerprint = DocumentContentFingerprint.model_validate(
                fingerprint.model_dump())
            if (fingerprint.object_key != doc['file_path'] or
                    (doc['file_size'] is not None and fingerprint.size != doc['file_size'])):
                raise PostingConflict('Content evidence does not match the locked document')
            content[doc['id']] = fingerprint.model_dump(mode='json')
        details['document_content'] = content
        version = 2
    return CaseBinding(context.org_id, ACTION, 'inventory.receipt.manifest',
        str(manifest_key), version, details)


def request_receipt_cost_review(db, context, actor_id, operation_key, *,
        manifest_key, declaration, reason, authorize, document_content):
    binding = receipt_cost_binding(db, context, manifest_key, declaration,
        authorize=authorize, document_content=document_content)
    if binding.source_version != 2:
        raise PermissionError('Version-pinned receipt cost evidence required')
    return request_case(db, context, actor_id, operation_key, binding=binding,
        reason=reason, load_binding=lambda session: receipt_cost_binding(session,
            context, manifest_key, declaration, authorize=authorize,
            document_content=document_content), authorize=authorize)


def review_receipt_cost(db, context, actor_id, operation_key, *, manifest_key,
        case_key, expected_version, outcome, reason, authorize):
    case = _owned(db, ManagerCase, context).filter_by(case_key=case_key,
        action=ACTION, source_type='inventory.receipt.manifest',
        source_key=str(manifest_key)).one_or_none()
    if case is None or case.source_version != 2:
        raise PermissionError('Version-pinned receipt cost review required')
    saved = CaseBinding(**case.binding)
    declaration = ReceiptCostDeclaration(**saved.details['declaration'])
    content = {key: DocumentContentFingerprint(**value)
        for key, value in saved.details['document_content'].items()}
    def load(session):
        current = receipt_cost_binding(session, context, manifest_key, declaration,
            authorize=authorize, reviewer_id=actor_id, document_content=content)
        if metadata_binding(current).snapshot() != metadata_binding(saved).snapshot():
            raise PostingConflict('Receipt cost evidence changed')
        return current
    binding = load(db)
    return review_case(db, context, actor_id, operation_key, case_key=case_key,
        binding=binding, expected_version=expected_version, outcome=outcome,
        reason=reason, load_binding=load, authorize=authorize)


def approved_receipt_cost_binding(db, context, case_key, manifest_key, *,
        authorize, document_content, replay_operation_key=None,
        replay_actor_id=None):
    """Return current approved version-pinned cost evidence for atomic use."""
    if not callable(authorize):
        raise ValueError('Receipt cost permission guard required')
    authorize(db)
    if replay_operation_key is not None or replay_actor_id is not None:
        if (not isinstance(replay_operation_key, UUID) or not replay_operation_key.int
                or type(replay_actor_id) is not int or replay_actor_id <= 0):
            raise ValueError('Replay requires exact receipt operation and actor identities')
    case = _owned(db, ManagerCase, context).filter_by(case_key=case_key,
        action=ACTION, source_type='inventory.receipt.manifest',
        source_key=str(manifest_key)).one_or_none()
    if case is None or case.source_version != 2:
        raise PermissionError('Approved version-pinned receipt cost evidence required')
    saved = CaseBinding(**case.binding)
    declaration = ReceiptCostDeclaration(**saved.details['declaration'])
    current = receipt_cost_binding(db, context, manifest_key, declaration,
        authorize=authorize, document_content=document_content)
    if current.snapshot() != saved.snapshot():
        raise PostingConflict('Reviewed receipt cost evidence changed')
    case = _owned(db, ManagerCase, context).filter_by(id=case.id).with_for_update().one()
    decision = _owned(db, ManagerCaseDecision, context).filter_by(
        case_id=case.id).one_or_none()
    if decision is None or decision.outcome != 'APPROVED':
        raise PermissionError('Receipt cost approval required')
    if decision.created_by in (case.created_by,
            current.details['manifest_created_by']):
        raise PermissionError('Independent receipt cost verification required')
    used = _owned(db, ManagerCaseUse, context).filter_by(
        case_id=case.id).one_or_none()
    if used is not None:
        if (replay_operation_key is None or used.operation_key != replay_operation_key
                or used.created_by != replay_actor_id):
            raise PostingConflict('Receipt cost approval has already been consumed')
        receipt = _owned(db, PostingOperation, context).filter_by(
            operation_key=replay_operation_key, created_by=replay_actor_id,
            kind=RECEIPT_POSTING_KIND).one_or_none()
        if receipt is None:
            raise PostingConflict('Consumed receipt cost approval lacks posting history')
    return current


def reviewed_receipt_cost_binding(db, context, case_key, manifest_key, *,
        authorize, replay_operation_key=None, replay_actor_id=None):
    """Resolve persisted fingerprints before storage reads; hashes stay server-owned."""
    case = _owned(db, ManagerCase, context).filter_by(case_key=case_key,
        action=ACTION, source_type='inventory.receipt.manifest',
        source_key=str(manifest_key)).one_or_none()
    if case is None or case.source_version != 2:
        raise PermissionError('Persisted version-pinned receipt cost review required')
    saved = CaseBinding(**case.binding)
    content = {key: DocumentContentFingerprint(**value)
        for key, value in saved.details.get('document_content', {}).items()}
    approved_receipt_cost_binding(db, context, case_key, manifest_key,
        authorize=authorize, document_content=content,
        replay_operation_key=replay_operation_key,
        replay_actor_id=replay_actor_id)
    return CaseBinding(**saved.snapshot())

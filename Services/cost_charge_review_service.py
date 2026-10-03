"""Evidence-bound review adapter shared by metadata and content-bound reviews.

No invoice duplication, new approval table, market-rate lookup, tax inference or
financial posting. The reviewer verifies declared eligibility against the linked
documents; database existence alone is not verification. Public adapters must gate
supplier/document/financial permissions BEFORE calling this service.
"""
from hashlib import sha256
from uuid import UUID
from sqlalchemy import and_, or_
from Model.containermgmt.Cinfo.Supplier import Supplier
from Model.containermgmt.Orders.OrderDocument import OrderDocument
from Model.containermgmt.Orders.PurchaseOrder import PurchaseOrder
from Model.containermgmt.Inventory.ManagerCase import ManagerCase, ManagerCaseDecision, ManagerCaseUse
from Model.containermgmt.Inventory.CostChargeUse import CostChargeUse
from Model.containermgmt.Inventory.PostingOperation import PostingOperation
from Schema.CostChargeSchema import CostChargeEvidence
from Schema.CostChargeReviewSchema import CostChargeDeclaration
from Schema.DocumentContentSchema import DocumentContentFingerprint
from Services.manager_case_service import CaseBinding
from Services.inventory_posting_service import PostingConflict, _json_snapshot
from Utils.org_filter import apply_org_filter

ACTION = 'inventory.cost.verify-charge'
CHARGE_POSTING_KIND = 'inventory.valuation.charge.v1'


def _charge_case(db, context, case_key, proposal_key):
    if context.org_id not in context.allowed_org_ids:
        raise PermissionError('Charge scope denied')
    case = apply_org_filter(db.query(ManagerCase).filter_by(org_id=context.org_id, case_key=case_key,
        source_key=str(proposal_key), source_type='inventory.cost-allocation', action=ACTION, is_deleted=False),
        ManagerCase, context).one_or_none()
    if case is None: raise PermissionError('Evidence-bound charge review required')
    return case


def reviewed_charge_binding(db, context, case_key, proposal_key, *, authorize, load_allocation,
                            replay_operation_key, replay_actor_id):
    """Load persisted approved source BEFORE file I/O; not proof of current bytes.

    Reuses the approval/source checker with saved fingerprints. The preparation
    service must then verify those original versions and posting must recheck all
    authority and source bindings. No client binding or digest is accepted here.
    """
    if not callable(authorize): raise ValueError('Explicit permission guard required')
    authorize(db)
    case = _charge_case(db, context, case_key, proposal_key)
    if case.source_version != 2:
        raise PermissionError('Persisted version-pinned review required')
    content = {key: DocumentContentFingerprint(**value)
               for key, value in case.binding['details'].get('document_content', {}).items()}
    approved_charge_evidence(db, context, case_key, proposal_key, authorize=authorize,
        load_allocation=load_allocation, document_content=content,
        replay_operation_key=replay_operation_key, replay_actor_id=replay_actor_id)
    return CaseBinding(**CaseBinding(**case.binding).snapshot())


def charge_review_binding(db, context, proposal_key, declaration, *, authorize, load_allocation, reviewer_id=None,
                          document_content=None):
    if not db.in_transaction(): raise ValueError('Evidence review requires an active transaction')
    if not callable(authorize) or not callable(load_allocation):
        raise ValueError('Explicit permission and allocation loaders required')
    if context.org_id not in context.allowed_org_ids: raise PermissionError('Charge scope denied')
    if not isinstance(proposal_key, UUID) or not proposal_key.int: raise ValueError('Nonzero proposal key required')
    if not isinstance(declaration, CostChargeDeclaration): raise ValueError('Typed charge declaration required')
    declaration = CostChargeDeclaration.model_validate(declaration.model_dump(mode='json'))
    authorize(db)
    # Shared parent locks before the proposal/case locks; select columns to avoid
    # eager supplier/payment relationships or copying unrelated sensitive fields.
    supplier = db.query(Supplier.supplier_id, Supplier.name, Supplier.updated_at).filter(
        Supplier.supplier_id == declaration.supplier_id, Supplier.is_deleted.is_(False), Supplier.is_active.is_(True),
        or_(and_(Supplier.is_shared.is_(False), Supplier.org_id == context.org_id),
            and_(Supplier.is_shared.is_(True), Supplier.org_id.is_(None)))).with_for_update(read=True).first()
    if supplier is None: raise PermissionError('Charge supplier unavailable in this company')
    ids = sorted({str(key) for key in (declaration.document_id, declaration.fx_document_id) if key})
    columns = ('id', 'entity_type', 'entity_id', 'po_id', 'payment_id', 'vendor_quote_id', 'doc_type',
               'title', 'file_name', 'file_path', 'file_size', 'mime_type', 'is_confidential', 'updated_at')
    query = db.query(*(getattr(OrderDocument, field) for field in columns)).filter(
        OrderDocument.id.in_(ids), OrderDocument.org_id == context.org_id, OrderDocument.is_deleted.is_(False))
    docs = apply_org_filter(query, OrderDocument, context).order_by(OrderDocument.id).with_for_update(read=True).all()
    if len(docs) != len(ids): raise PermissionError('Charge documents unavailable in this company')
    order_ids = sorted({doc.po_id for doc in docs if doc.po_id is not None})
    orders = []
    if order_ids:
        order_query = db.query(PurchaseOrder.id, PurchaseOrder.supplier_id, PurchaseOrder.lifecycle_version,
            PurchaseOrder.updated_at).filter(PurchaseOrder.id.in_(order_ids), PurchaseOrder.org_id == context.org_id,
                PurchaseOrder.is_deleted.is_(False))
        rows = apply_org_filter(order_query, PurchaseOrder, context).order_by(PurchaseOrder.id).with_for_update(read=True).all()
        if len(rows) != len(order_ids): raise PermissionError('Evidence purchase order unavailable in this company')
        invoice = next(doc for doc in docs if str(doc.id) == str(declaration.document_id))
        for row in rows:
            if row.id == invoice.po_id and row.supplier_id != declaration.supplier_id:
                raise PostingConflict('Invoice purchase order supplier does not match the declared issuer')
            orders.append(dict(id=row.id, supplier_id=row.supplier_id, lifecycle_version=row.lifecycle_version,
                updated_at=row.updated_at.isoformat() if row.updated_at else None))
    allocation = load_allocation(db)
    if not isinstance(allocation, CaseBinding) or allocation.org_id != context.org_id or \
            allocation.action != 'inventory.cost.allocate' or allocation.source_type != 'inventory.cost-allocation' or \
            allocation.source_key != str(proposal_key):
        raise PostingConflict('Exact authoritative allocation binding required')
    if reviewer_id == allocation.details['creator_id']:
        raise PermissionError('Proposal creators cannot verify their own charge')
    if declaration.amount_scr() != allocation.details['snapshot']['total_scr']:
        raise PostingConflict('Converted eligible charge must equal the complete allocation')
    documents = []
    for doc in docs:
        snapshot = dict(doc._mapping)
        snapshot['updated_at'] = snapshot['updated_at'].isoformat() if snapshot['updated_at'] else None
        documents.append(snapshot)
    details = dict(allocation=allocation.snapshot(), declaration=declaration.model_dump(mode='json'),
            calculation_policy='charge-fx-v1', amount_scr=declaration.amount_scr(),
            supplier=dict(id=supplier.supplier_id, name=supplier.name,
                updated_at=supplier.updated_at.isoformat() if supplier.updated_at else None), documents=documents, orders=orders)
    # Prepared by a trusted owning adapter BEFORE the posting transaction. Never
    # perform storage I/O inside manager-case callbacks or accept client digests.
    version = 1
    if document_content is not None:
        if not isinstance(document_content, dict) or set(document_content) != set(ids):
            raise PostingConflict('Content evidence must cover exactly the linked documents')
        content = {}
        for doc in documents:
            fingerprint = document_content[doc['id']]
            if not isinstance(fingerprint, DocumentContentFingerprint):
                raise ValueError('Typed server-prepared content fingerprint required')
            fingerprint = DocumentContentFingerprint.model_validate(fingerprint.model_dump())
            if fingerprint.object_key != doc['file_path'] or (doc['file_size'] is not None and fingerprint.size != doc['file_size']):
                raise PostingConflict('Content evidence does not match the locked document')
            content[doc['id']] = fingerprint.model_dump(mode='json')
        details['document_content'] = content
        version = 2
    return CaseBinding(context.org_id, ACTION, allocation.source_type, str(proposal_key), version, details)


def approved_charge_evidence(db, context, case_key, proposal_key, *, authorize, load_allocation, document_content=None,
                             replay_operation_key=None, replay_actor_id=None):
    """Load approved, current, unconsumed evidence; not permission to post.

The caller must still consume the SAME case and charge with valuation atomically.
The trusted adapter must re-read the pinned versions outside the posting transaction
and supply their typed fingerprints, never client-provided hashes. Public capture,
retention guarantees and central authority remain release gates.
"""
    if not callable(authorize): raise ValueError('Explicit permission guard required')
    authorize(db)
    if replay_operation_key is not None or replay_actor_id is not None:
        if not isinstance(replay_operation_key, UUID) or not replay_operation_key.int or type(replay_actor_id) is not int or replay_actor_id <= 0:
            raise ValueError('Replay requires an exact nonzero operation key and authenticated actor')
    case = _charge_case(db, context, case_key, proposal_key)
    if case.source_version != 2 or document_content is None:
        raise PermissionError('Version-pinned content review and current server verification required')
    current = charge_review_binding(db, context, proposal_key, CostChargeDeclaration(**case.binding['details']['declaration']),
        authorize=authorize, load_allocation=load_allocation, document_content=document_content)
    if current.snapshot() != case.binding: raise PostingConflict('Reviewed charge evidence changed')
    case = db.query(ManagerCase).filter_by(id=case.id, org_id=context.org_id).with_for_update().one()
    decision = db.query(ManagerCaseDecision).filter_by(org_id=context.org_id, case_id=case.id, is_deleted=False).one_or_none()
    if decision is None or decision.outcome != 'APPROVED': raise PermissionError('Charge verification approval required')
    if decision.created_by in (case.created_by, current.details['allocation']['details']['creator_id']):
        raise PermissionError('Independent charge verification required')
    _, encoded = _json_snapshot(current.snapshot())
    declared = current.details['declaration']
    evidence = CostChargeEvidence(supplier_id=declared['supplier_id'], invoice_reference=declared['invoice_reference'],
        document_id=declared['document_id'], source_fingerprint=sha256(encoded.encode()).hexdigest(),
        amount_scr=current.details['amount_scr'])
    used = apply_org_filter(db.query(ManagerCaseUse).filter_by(org_id=context.org_id,
        case_id=case.id, is_deleted=False), ManagerCaseUse, context).one_or_none()
    if used is not None:
        if replay_operation_key is None or used.operation_key != replay_operation_key or used.created_by != replay_actor_id:
            raise PostingConflict('Charge verification has already been consumed')
        receipt = apply_org_filter(db.query(PostingOperation.id).filter_by(org_id=context.org_id,
            operation_key=replay_operation_key, created_by=replay_actor_id, kind=CHARGE_POSTING_KIND,
            is_deleted=False), PostingOperation, context).one_or_none()
        charge = apply_org_filter(db.query(CostChargeUse).filter_by(org_id=context.org_id,
            operation_key=replay_operation_key, created_by=replay_actor_id, proposal_key=proposal_key,
            is_deleted=False), CostChargeUse, context).one_or_none()
        if receipt is None or charge is None or charge.evidence != evidence.model_dump(mode='json'):
            raise PostingConflict('Consumed evidence lacks matching charge-posting history')
    # This is a guard result only. The outer posting boundary must still compare
    # the complete request digest and return its receipt; never execute another effect.
    return evidence

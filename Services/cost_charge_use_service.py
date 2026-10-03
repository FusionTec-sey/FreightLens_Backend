"""Internal whole-charge deduplication inside a caller-owned posting transaction.

The trusted evidence loader must lock/revalidate the approved supplier invoice,
capitalisable amount and FX evidence; an attachment or reference alone is NOT
verification. Authorize must check permissions, central authority and approvals.
There is deliberately no public adapter until those integrations exist.
Call check_cost_charge in the OUTER posting guard on every attempt/replay, then
consume_cost_charge inside its domain effect alongside valuation and case use.
Neither helper commits, creates a posting receipt or writes a valuation.
"""
from hashlib import sha256
from uuid import UUID
from sqlalchemy import text, or_, and_
from Model.containermgmt.Inventory.CostChargeUse import CostChargeUse
from Model.containermgmt.Inventory.CostAllocation import CostAllocationProposal
from Model.containermgmt.Cinfo.Supplier import Supplier
from Model.containermgmt.Orders.OrderDocument import OrderDocument
from Schema.CostChargeSchema import CostChargeEvidence, invoice_identity
from Services.inventory_posting_service import PostingConflict
from Utils.org_filter import apply_org_filter


def check_cost_charge(db, context, actor_id, operation_key, proposal_key, expected, *, authorize, load_evidence):
    if not db.in_transaction(): raise ValueError('Charge use requires an active transaction')
    if not callable(authorize) or not callable(load_evidence):
        raise ValueError('Permission/authority/approval and verified evidence loaders are mandatory')
    if context.org_id not in context.allowed_org_ids: raise PermissionError('Charge scope denied')
    if type(actor_id) is not int or actor_id <= 0: raise ValueError('Authenticated actor required')
    if any(not isinstance(key, UUID) or not key.int for key in (operation_key, proposal_key)):
        raise ValueError('Nonzero operation and proposal keys required')
    if not isinstance(expected, CostChargeEvidence): raise ValueError('Typed expected evidence required')
    if CostChargeEvidence.model_validate(expected.model_dump(mode='json')) != expected:
        raise ValueError('Canonical validated evidence required')
    authorize(db)
    actual = load_evidence(db)
    if not isinstance(actual, CostChargeEvidence) or actual != expected:
        raise PostingConflict('Verified charge evidence changed')
    identity = invoice_identity(expected.invoice_reference)
    lock = int.from_bytes(sha256(f'cost-charge-v1:{context.org_id}:{expected.supplier_id}:{identity}'.encode()).digest()[:8], 'big', signed=True)
    if db.execute(text('SHOW transaction_isolation')).scalar() != 'read committed':
        raise ValueError('Charge use requires READ COMMITTED isolation')
    db.execute(text("SET LOCAL lock_timeout = '5s'"))
    db.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': lock})
    supplier = db.query(Supplier.supplier_id).filter(Supplier.supplier_id == expected.supplier_id,
        Supplier.is_deleted.is_(False), Supplier.is_active.is_(True), or_(
            and_(Supplier.is_shared.is_(False), Supplier.org_id == context.org_id),
            and_(Supplier.is_shared.is_(True), Supplier.org_id.is_(None)))).with_for_update(read=True).first()
    document = apply_org_filter(db.query(OrderDocument.id).filter(OrderDocument.id == str(expected.document_id),
        OrderDocument.org_id == context.org_id, OrderDocument.is_deleted.is_(False)), OrderDocument, context).with_for_update(read=True).first()
    proposal = apply_org_filter(db.query(CostAllocationProposal).filter_by(proposal_key=proposal_key,
        org_id=context.org_id, is_deleted=False), CostAllocationProposal, context).populate_existing().with_for_update().one_or_none()
    if supplier is None or document is None or proposal is None:
        raise PermissionError('Charge source unavailable in this company')
    if proposal.snapshot['total_scr'] != expected.amount_scr:
        raise PostingConflict('Proposal must allocate the whole verified eligible charge')
    # One whole charge per invoice, proposal and evidence document. No splitting
    # or multi-invoice document consumption until explicit reviewed lineage exists.
    previous = apply_org_filter(db.query(CostChargeUse).filter(CostChargeUse.org_id == context.org_id,
        CostChargeUse.is_deleted.is_(False), or_(
            and_(CostChargeUse.supplier_id == expected.supplier_id, CostChargeUse.invoice_identity == identity),
            CostChargeUse.proposal_key == proposal_key,
            CostChargeUse.document_id == str(expected.document_id))), CostChargeUse, context).limit(3).all()
    if previous:
        if len(previous) != 1 or previous[0].operation_key != operation_key or previous[0].created_by != actor_id or \
                previous[0].proposal_key != proposal_key or previous[0].evidence != expected.model_dump(mode='json'):
            raise PostingConflict('Supplier charge or allocation proposal has already been consumed')
        return previous[0]
    return None


def consume_cost_charge(db, context, actor_id, operation_key, proposal_key, expected, *, authorize, load_evidence):
    previous = check_cost_charge(db, context, actor_id, operation_key, proposal_key, expected,
        authorize=authorize, load_evidence=load_evidence)
    if previous is not None:
        raise PostingConflict('Charge already consumed; replay belongs to the outer posting receipt')
    row = CostChargeUse(org_id=context.org_id, operation_key=operation_key, supplier_id=expected.supplier_id,
        invoice_identity=invoice_identity(expected.invoice_reference), document_id=str(expected.document_id),
        proposal_key=proposal_key, amount_scr=expected.amount_scr, evidence=expected.model_dump(mode='json'), created_by=actor_id)
    db.add(row); db.flush()
    return row

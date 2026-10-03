from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4
import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from Model.containermgmt.Cinfo.Supplier import Supplier
from Model.containermgmt.Orders.OrderDocument import OrderDocument
from Model.containermgmt.Inventory.CostChargeUse import CostChargeUse
from Schema.CostChargeSchema import CostChargeEvidence, invoice_identity
from Services.cost_charge_use_service import check_cost_charge, consume_cost_charge
from Services.inventory_posting_service import execute_once, PostingEffect, PostingConflict
from Utils.org_filter import OrgContext
from tests.test_cost_allocation_proposals import allocation  # noqa: F401
from tests.test_inventory_valuation import valued  # noqa: F401
from tests.test_stock_ledger import stock  # noqa: F401


@pytest.fixture
def charge(allocation, monkeypatch):
    from Utils import migrate_20261003_cost_charge_uses as migration
    f = allocation; f.save_proposal()
    monkeypatch.setattr(migration, 'engine', f.factory.kw['bind']); migration.ensure_cost_charge_uses_schema()
    with f.factory.begin() as db:
        supplier = Supplier(org_id=f.orgs[0], name='Synthetic charge issuer', is_shared=False)
        document = OrderDocument(org_id=f.orgs[0], entity_type='GENERAL', doc_type='OTHER',
            file_name='synthetic.pdf', file_path='synthetic/not-a-real-file', created_by=f.actor)
        db.add_all([supplier, document]); db.flush()
        f.evidence = CostChargeEvidence(supplier_id=supplier.supplier_id, invoice_reference='TEST-001',
            document_id=document.id, source_fingerprint='a' * 64, amount_scr='12.34')
    f.charge_key = uuid4()
    def post(*, key=None, proposal=None, evidence=None, context=None, authorize=lambda db: None,
             load=None, factory=None, fail=False):
        key, proposal, evidence, context = key or f.charge_key, proposal or f.payload.operation_key, evidence or f.evidence, context or f.context
        kwargs = dict(authorize=authorize, load_evidence=load or (lambda db: evidence))
        def guard(db): check_cost_charge(db, context, f.actor, key, proposal, evidence, **kwargs)
        def apply(db):
            consume_cost_charge(db, context, f.actor, key, proposal, evidence, **kwargs)
            if fail: raise RuntimeError('Synthetic coordinator failure')
            return PostingEffect({'claimed': True}, {'kind': 'test.charge-used'})
        return execute_once(factory or f.factory, context, f.actor, key, 'test.charge-use',
            {'proposal_key': str(proposal), 'evidence': evidence.model_dump(mode='json')}, apply, authorize=guard)
    f.post_charge = post
    return f


@pytest.mark.parametrize('reference', ['TEST-001', 'test 001', 'TEST/001', 'TEST_001', 'TEST.001'])
def test_identity_is_conservative_but_preserves_leading_zeros(reference):
    assert invoice_identity(reference) == 'TEST001'
    assert invoice_identity('TEST-01') != invoice_identity('TEST-001')


@pytest.mark.parametrize('change', [{'invoice_reference': '---'}, {'invoice_reference': 'INV\n01'},
    {'invoice_reference': '发票001'}, {'amount_scr': 'NaN'}, {'amount_scr': 'bad'}, {'amount_scr': '0'},
    {'amount_scr': '1.0000001'}, {'amount_scr': 1.2}, {'supplier_id': True}, {'source_fingerprint': 'unverified'}])
def test_invalid_evidence_rejected(change):
    with pytest.raises(ValidationError): CostChargeEvidence(**dict(supplier_id=1, invoice_reference='INV-01',
        document_id=uuid4(), source_fingerprint='a'*64, amount_scr='1') | change)


def test_claim_replay_and_permission_revocation(charge):
    f = charge
    assert not f.post_charge().replayed
    assert f.post_charge().replayed
    def deny(db): raise PermissionError('revoked')
    with pytest.raises(PermissionError): f.post_charge(authorize=deny)
    with pytest.raises(ValueError): f.post_charge(authorize=None)
    with pytest.raises(PostingConflict): f.post_charge(load=lambda db: f.evidence.model_copy(update={'source_fingerprint': 'b'*64}))


@pytest.mark.parametrize('same_key', [True, False])
def test_concurrent_same_charge_has_one_effect(charge, same_key):
    f = charge; barrier = Barrier(2)
    def post(index):
        barrier.wait(timeout=10)
        try: return f.post_charge(key=f.charge_key if same_key or index == 0 else uuid4()).replayed
        except PostingConflict: return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as executor: results = list(executor.map(post, range(2)))
    assert results.count(False) == 1 and results.count(True if same_key else 'conflict') == 1
    with f.factory() as db: assert db.query(CostChargeUse).filter_by(org_id=f.orgs[0]).count() == 1


def test_same_invoice_new_document_and_new_proposal_cannot_bypass_dedup(charge):
    f = charge; f.post_charge()
    other = f.payload.model_copy(update={'operation_key': uuid4()}); f.save_proposal(other)
    with f.factory.begin() as db:
        document = OrderDocument(org_id=f.orgs[0], entity_type='GENERAL', doc_type='OTHER',
            file_name='another-upload.pdf', file_path='synthetic/second', created_by=f.actor)
        db.add(document); db.flush(); key = document.id
    evidence = CostChargeEvidence(**{**f.evidence.model_dump(), 'document_id': key, 'invoice_reference': 'test / 001'})
    with pytest.raises(PostingConflict): f.post_charge(key=uuid4(), proposal=other.operation_key, evidence=evidence)


def test_proposal_cannot_consume_a_second_invoice(charge):
    f = charge; f.post_charge()
    evidence = f.evidence.model_copy(update={'invoice_reference': 'ANOTHER-CHARGE'})
    with pytest.raises(PostingConflict): f.post_charge(key=uuid4(), evidence=evidence)


def test_document_cannot_be_relabelled_as_another_charge(charge):
    f = charge; f.post_charge()
    other = f.payload.model_copy(update={'operation_key': uuid4()}); f.save_proposal(other)
    evidence = f.evidence.model_copy(update={'invoice_reference': 'ANOTHER-CHARGE'})
    with pytest.raises(PostingConflict): f.post_charge(key=uuid4(), proposal=other.operation_key, evidence=evidence)


def test_concurrent_different_invoice_claims_cannot_reuse_proposal(charge):
    f = charge; barrier = Barrier(2)
    def post(index):
        evidence = f.evidence.model_copy(update={'invoice_reference': f'DIFFERENT-{index}'})
        barrier.wait(timeout=10)
        try: f.post_charge(key=uuid4(), evidence=evidence); return 'saved'
        except PostingConflict: return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(post, range(2))) == ['conflict', 'saved']


def test_database_rejects_duplicate_without_service_guard(charge):
    f = charge; f.post_charge()
    other = f.payload.model_copy(update={'operation_key': uuid4()}); f.save_proposal(other)
    with f.factory.begin() as db, pytest.raises(DBAPIError):
        db.add(CostChargeUse(org_id=f.orgs[0], operation_key=uuid4(), supplier_id=f.evidence.supplier_id,
            invoice_identity=invoice_identity(f.evidence.invoice_reference), document_id=str(f.evidence.document_id),
            proposal_key=other.operation_key, amount_scr=f.evidence.amount_scr,
            evidence=f.evidence.model_dump(mode='json'), created_by=f.actor))
        db.flush()


def test_database_rejects_foreign_sources_without_service_guard(charge):
    f = charge
    with f.factory.begin() as db, pytest.raises(DBAPIError):
        db.add(CostChargeUse(org_id=f.orgs[1], operation_key=uuid4(), supplier_id=f.evidence.supplier_id,
            invoice_identity=invoice_identity(f.evidence.invoice_reference), document_id=str(f.evidence.document_id),
            proposal_key=f.payload.operation_key, amount_scr=f.evidence.amount_scr,
            evidence=f.evidence.model_dump(mode='json'), created_by=f.actor))
        db.flush()


def test_charge_identity_is_company_wide_not_cost_pool_scoped(charge):
    from Model.containermgmt.Inventory.CostPool import InventoryCostPool
    from Model.containermgmt.Inventory.CostAllocation import CostAllocationProposal
    f = charge; f.post_charge(); other_key = uuid4()
    def add(db):
        pool = InventoryCostPool(org_id=f.orgs[0], code='OTHER', name='Synthetic other pool', created_by=f.actor)
        db.add(pool); db.flush()
        original = db.get(CostAllocationProposal, f.payload.operation_key)
        db.add(CostAllocationProposal(org_id=f.orgs[0], proposal_key=other_key, cost_pool_id=pool.id,
            manifest=original.manifest, snapshot=original.snapshot, created_by=f.actor))
        return PostingEffect({}, {'kind': 'test.other-pool-proposal'})
    execute_once(f.factory, f.context, f.actor, other_key, 'test.proposal', {}, add, authorize=lambda db: None)
    with pytest.raises(PostingConflict): f.post_charge(key=uuid4(), proposal=other_key)


def test_same_invoice_number_from_different_supplier_is_independent(charge):
    f = charge; f.post_charge()
    other = f.payload.model_copy(update={'operation_key': uuid4()}); f.save_proposal(other)
    with f.factory.begin() as db:
        supplier = Supplier(org_id=f.orgs[0], name='Other synthetic supplier', is_shared=False)
        document = OrderDocument(org_id=f.orgs[0], entity_type='GENERAL', doc_type='OTHER',
            file_name='other.pdf', file_path='synthetic/other', created_by=f.actor)
        db.add_all([supplier, document]); db.flush()
        evidence = CostChargeEvidence(**{**f.evidence.model_dump(), 'supplier_id': supplier.supplier_id, 'document_id': document.id})
    assert not f.post_charge(key=uuid4(), proposal=other.operation_key, evidence=evidence).replayed


def test_partial_charge_amount_is_blocked(charge):
    f = charge
    with pytest.raises(PostingConflict): f.post_charge(evidence=f.evidence.model_copy(update={'amount_scr': '1.000000'}))


def test_outer_failure_releases_charge_for_retry(charge):
    f = charge
    with pytest.raises(RuntimeError): f.post_charge(fail=True)
    with f.factory() as db: assert db.query(CostChargeUse).filter_by(org_id=f.orgs[0]).count() == 0
    with pytest.raises(RuntimeError):
        with f.factory.begin() as db:
            f.post_charge(factory=db)
            raise RuntimeError('Failure after domain effect')
    assert not f.post_charge().replayed


@pytest.mark.parametrize('scope', ['company', 'document', 'supplier'])
def test_foreign_scope_never_falls_back(charge, scope):
    f = charge
    if scope == 'company':
        foreign = OrgContext(current_org_id=f.orgs[1], allowed_org_ids=f.orgs, is_root=True)
        with pytest.raises(PermissionError): f.post_charge(context=foreign)
    else:
        with f.factory.begin() as db:
            row = db.get(OrderDocument, str(f.evidence.document_id)) if scope == 'document' else db.get(Supplier, f.evidence.supplier_id)
            row.org_id = f.orgs[1]
        with pytest.raises(PermissionError): f.post_charge()


@pytest.mark.parametrize('operation', ['UPDATE containermgmt.inventory_cost_charge_uses SET amount_scr=amount_scr',
    'DELETE FROM containermgmt.inventory_cost_charge_uses'])
def test_claim_is_immutable_in_database(charge, operation):
    f = charge; f.post_charge()
    with f.factory.begin() as db, pytest.raises(DBAPIError):
        db.execute(text(operation + ' WHERE operation_key=:key'), {'key': f.charge_key})


def test_claim_cannot_commit_without_outer_receipt(charge):
    f = charge
    with pytest.raises(DBAPIError):
        with f.factory.begin() as db:
            consume_cost_charge(db, f.context, f.actor, f.charge_key, f.payload.operation_key, f.evidence,
                authorize=lambda db: None, load_evidence=lambda db: f.evidence)
    assert not f.post_charge().replayed


def test_migration_replays_without_claiming_real_charges(charge, monkeypatch):
    from Utils import migrate_20261003_cost_charge_uses as migration
    f = charge; monkeypatch.setattr(migration, 'engine', f.factory.kw['bind'])
    migration.ensure_cost_charge_uses_schema(); migration.ensure_cost_charge_uses_schema()
    with f.factory() as db: assert db.query(CostChargeUse).filter_by(org_id=f.orgs[0]).count() == 0

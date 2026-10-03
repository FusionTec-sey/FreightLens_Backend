from datetime import date
from decimal import localcontext
from uuid import uuid4
import pytest
from pydantic import ValidationError
from Model.Credentials.users import User
from Model.containermgmt.Orders.OrderDocument import OrderDocument
from Schema.CostChargeReviewSchema import CostChargeDeclaration
from Services.cost_charge_review_service import charge_review_binding, approved_charge_evidence
from Services.manager_case_service import request_case, review_case
from Services.inventory_posting_service import PostingConflict
from Utils.org_filter import OrgContext
from tests.test_cost_charge_uses import charge  # noqa: F401
from tests.test_cost_allocation_proposals import allocation  # noqa: F401
from tests.test_inventory_valuation import valued  # noqa: F401
from tests.test_stock_ledger import stock  # noqa: F401


def declaration(**changes):
    return CostChargeDeclaration(**dict(supplier_id=1, invoice_reference='INV-1', invoice_date=date(2026, 10, 3),
        document_id=uuid4(), source_currency='SCR', eligible_amount='12.34', exchange_rate_to_scr='1',
        capitalisation_reason='Eligible transport expense') | changes)


@pytest.mark.parametrize('changes', [dict(source_currency='USD'), dict(source_currency='SCR', exchange_rate_to_scr='2'),
    dict(eligible_amount='NaN'), dict(eligible_amount='0'), dict(eligible_amount=1.2), dict(exchange_rate_to_scr='NaN'),
    dict(exchange_rate_to_scr='0'), dict(exchange_rate_to_scr='1.000000001'), dict(source_currency='usd'),
    dict(capitalisation_reason=' '), dict(invoice_reference='--'), dict(eligible_amount='999999999999999999.999999',
        source_currency='USD', exchange_rate_to_scr='2', fx_document_id=uuid4())])
def test_declaration_rejects_missing_or_inexact_evidence(changes):
    with pytest.raises(ValidationError): declaration(**changes)


def test_conversion_has_explicit_direction_rounding_and_isolated_decimal_context():
    with localcontext() as ctx:
        ctx.prec = 2
        value = declaration(source_currency='USD', eligible_amount='1.000001', exchange_rate_to_scr='12.34567891', fx_document_id=uuid4())
        assert value.amount_scr() == '12.345691'
    assert declaration().eligible_amount == '12.340000'
    assert declaration().exchange_rate_to_scr == '1.00000000'


@pytest.fixture
def charge_review(charge):
    from Routes.Inventory.CostPoolRouter import allocation_binding
    f = charge
    with f.factory.begin() as db:
        user = User(username='charge-' + uuid4().hex, password_hash='test-only', org_id=f.orgs[0])
        db.add(user); db.flush(); f.reviewer = user.id
    f.declaration = declaration(supplier_id=f.evidence.supplier_id, document_id=f.evidence.document_id)
    f.load_allocation = lambda db: allocation_binding(db, f.context, f.pool, f.payload.operation_key)
    f.case_key = uuid4(); f.decision_key = uuid4()
    def load(db, *, actor=None, context=None, declared=None, authorize=lambda db: None):
        return charge_review_binding(db, context or f.context, f.payload.operation_key, declared or f.declaration,
            authorize=authorize, load_allocation=f.load_allocation, reviewer_id=actor)
    f.load_charge = load
    with f.factory.begin() as db:
        f.binding = load(db)
        request_case(db, f.context, f.actor, f.case_key, binding=f.binding, reason='Synthetic verify invoice and FX',
            load_binding=load, authorize=lambda db: None)
    def decide(actor=None, outcome='APPROVED'):
        with f.factory.begin() as db:
            return review_case(db, f.context, actor or f.reviewer, f.decision_key, case_key=f.case_key,
                binding=f.binding, expected_version=1, outcome=outcome, reason='Synthetic evidence checked',
                load_binding=lambda session: load(session, actor=actor or f.reviewer), authorize=lambda db: None)
    def evidence(case_key=None, authorize=lambda db: None):
        with f.factory.begin() as db:
            return approved_charge_evidence(db, f.context, case_key or f.case_key, f.payload.operation_key,
                authorize=authorize, load_allocation=f.load_allocation)
    f.decide, f.verified_evidence = decide, evidence
    return f


def test_only_independently_approved_current_evidence_can_be_loaded(charge_review):
    f = charge_review
    with pytest.raises(PermissionError): f.verified_evidence()
    with pytest.raises(PermissionError): f.decide(actor=f.actor)
    assert not f.decide().replayed
    assert f.decide().replayed
    # Historical metadata-only reviews remain readable/decidable but never gain
    # financial evidence authority without a new version-pinned request.
    with pytest.raises(PermissionError): f.verified_evidence()


def test_rejection_cannot_supply_verified_evidence(charge_review):
    f = charge_review; f.decide(outcome='REJECTED')
    with pytest.raises(PermissionError): f.verified_evidence()


@pytest.mark.parametrize('field,value', [('file_path', 'changed/object'), ('file_size', 765), ('is_deleted', True)])
def test_document_changes_invalidate_review_and_approved_loader(charge_review, field, value):
    f = charge_review; f.decide()
    with f.factory.begin() as db: setattr(db.get(OrderDocument, str(f.evidence.document_id)), field, value)
    with pytest.raises((PostingConflict, PermissionError)): f.decide()
    with pytest.raises((PostingConflict, PermissionError)): f.verified_evidence()


def test_allocation_only_approval_is_not_charge_verification(charge_review):
    f = charge_review; key = uuid4()
    with f.factory.begin() as db:
        binding = f.load_allocation(db)
        request_case(db, f.context, f.actor, key, binding=binding, reason='Allocation only',
            load_binding=f.load_allocation, authorize=lambda db: None)
        review_case(db, f.context, f.reviewer, uuid4(), case_key=key, binding=binding, expected_version=1,
            outcome='APPROVED', reason='Allocation only', load_binding=f.load_allocation, authorize=lambda db: None)
    with pytest.raises(PermissionError): f.verified_evidence(case_key=key)


def test_permission_checked_before_any_source_reads(charge_review):
    f = charge_review
    def deny(db): raise PermissionError('revoked')
    with f.factory.begin() as db, pytest.raises(PermissionError): f.load_charge(db, authorize=deny)
    with pytest.raises(PermissionError): f.verified_evidence(authorize=deny)


def test_foreign_documents_and_company_cannot_be_reviewed(charge_review):
    f = charge_review
    foreign = OrgContext(current_org_id=f.orgs[1], allowed_org_ids=f.orgs, is_root=True)
    with f.factory.begin() as db, pytest.raises(PermissionError): f.load_charge(db, context=foreign)
    with f.factory.begin() as db: db.get(OrderDocument, str(f.evidence.document_id)).org_id = f.orgs[1]
    with f.factory.begin() as db, pytest.raises(PermissionError): f.load_charge(db)


def test_foreign_currency_evidence_and_exact_total_are_bound(charge_review):
    f = charge_review
    with f.factory.begin() as db:
        doc = OrderDocument(org_id=f.orgs[0], entity_type='GENERAL', doc_type='OTHER',
            file_name='fx.pdf', file_path='synthetic/fx', created_by=f.actor)
        db.add(doc); db.flush(); fx_id = doc.id
    declared = declaration(supplier_id=f.evidence.supplier_id, document_id=f.evidence.document_id,
        source_currency='USD', eligible_amount='1', exchange_rate_to_scr='12.34', fx_document_id=fx_id)
    with f.factory.begin() as db:
        bound = f.load_charge(db, declared=declared)
        assert len(bound.details['documents']) == 2
        assert bound.details['amount_scr'] == '12.340000'
        with pytest.raises(PostingConflict):
            f.load_charge(db, declared=declared.model_copy(update={'exchange_rate_to_scr': '12.35'}))


@pytest.mark.parametrize('foreign', [False, True])
def test_invoice_parent_must_have_matching_company_and_supplier(charge_review, foreign):
    from Model.containermgmt.Orders.PurchaseOrder import PurchaseOrder
    f = charge_review
    with f.factory.begin() as db:
        order = PurchaseOrder(org_id=f.orgs[1] if foreign else f.orgs[0], po_number='SYN-' + uuid4().hex,
            supplier_id=None if not foreign else f.evidence.supplier_id, created_by=f.actor)
        db.add(order); db.flush()
        db.get(OrderDocument, str(f.evidence.document_id)).po_id = order.id
    with f.factory.begin() as db, pytest.raises(PermissionError if foreign else PostingConflict): f.load_charge(db)


def test_consumed_evidence_case_is_not_available_to_another_posting(charge_review):
    from Services.manager_case_service import consume_case
    from Services.inventory_posting_service import execute_once, PostingEffect
    f = charge_review; f.decide(); key = uuid4()
    def consume(db):
        consume_case(db, f.context, f.actor, key, case_key=f.case_key, binding=f.binding,
            load_binding=f.load_charge, authorize=lambda db: None)
        return PostingEffect({}, {'kind': 'test.consume-charge-review'})
    execute_once(f.factory, f.context, f.actor, key, 'test.charge-review-use', {}, consume, authorize=lambda db: None)
    with pytest.raises((PermissionError, PostingConflict)): f.verified_evidence()

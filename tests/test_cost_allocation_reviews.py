from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4
import pytest
from fastapi import HTTPException
from Model.Credentials.users import User
from Model.containermgmt.Inventory.ManagerCase import ManagerCaseDecision
from Model.containermgmt.Inventory.Valuation import InventoryValuation
from Model.containermgmt.Orders.Product import Product
from Schema.CostAllocationSchema import CostAllocationReviewRequest, CostAllocationCaseRead
from Schema.ManagerCaseSchema import PolicyCaseReview
from Utils.org_filter import OrgContext
from tests.test_cost_allocation_proposals import allocation  # noqa: F401
from tests.test_inventory_valuation import valued  # noqa: F401
from tests.test_stock_ledger import stock  # noqa: F401


@pytest.fixture
def reviewed(allocation):
    from Routes.Inventory.CostPoolRouter import request_allocation_review, review_allocation
    f = allocation; f.save_proposal()
    with f.factory.begin() as db:
        users = [User(username='cost-review-' + uuid4().hex, password_hash='test-only', org_id=f.orgs[0]) for _ in range(2)]
        db.add_all(users); db.flush(); f.requester, f.reviewer = [u.id for u in users]
    f.request = CostAllocationReviewRequest(operation_key=uuid4(), reason='Review synthetic allocation')
    f.decision = PolicyCaseReview(operation_key=uuid4(), expected_version=1, outcome='APPROVED', reason='Synthetic independent review')
    def request(actor=None, context=None):
        with f.factory() as db:
            return request_allocation_review(f.pool, f.payload.operation_key, f.request, db=db,
                context=context or f.context, user=SimpleNamespace(id=actor or f.requester))
    def review(actor=None, payload=None, context=None):
        with f.factory() as db:
            return review_allocation(f.pool, f.payload.operation_key, f.request.operation_key, payload or f.decision,
                db=db, context=context or f.context, user=SimpleNamespace(id=actor or f.reviewer))
    f.request_review, f.review = request, review
    return f


def test_exact_review_replay_history_and_no_capitalisation(reviewed):
    from Routes.Inventory.CostPoolRouter import list_allocation_reviews
    f = reviewed
    assert not f.request_review().replayed
    assert f.request_review().replayed
    assert not f.review().replayed
    assert f.review().replayed
    with f.factory() as db:
        page = list_allocation_reviews(f.pool, f.payload.operation_key, page=1, limit=1, view='ALL',
            db=db, context=f.context, user=SimpleNamespace(id=f.reviewer))
        case = CostAllocationCaseRead(**page['items'][0])
        assert case.status == 'APPROVED' and case.creator_id == f.actor
        assert case.snapshot.total_scr == '12.340000' and not case.snapshot.posting_enabled
        assert db.query(InventoryValuation).filter_by(org_id=f.orgs[0]).count() == 1


@pytest.mark.parametrize('actor', ['actor', 'requester'])
def test_creator_and_proxy_requester_cannot_self_review(reviewed, actor):
    from Routes.Inventory.CostPoolRouter import list_allocation_reviews
    f = reviewed; f.request_review()
    with pytest.raises(HTTPException) as error: f.review(actor=getattr(f, actor))
    assert error.value.status_code == 403
    with f.factory() as db:
        page = list_allocation_reviews(f.pool, f.payload.operation_key, page=1, limit=25, view='NEEDS_MY_REVIEW',
            db=db, context=f.context, user=SimpleNamespace(id=getattr(f, actor)))
        assert page['total'] == 0


def test_changed_source_blocks_review_and_replay(reviewed):
    f = reviewed; f.request_review(); f.review()
    with f.factory.begin() as db: db.get(Product, f.products[0]).name = 'Changed source label'
    with pytest.raises(HTTPException) as error: f.review()
    assert error.value.status_code == 409


@pytest.mark.parametrize('action', ['request', 'review', 'list'])
def test_foreign_company_denied_even_with_root_fallback(reviewed, action):
    from Routes.Inventory.CostPoolRouter import list_allocation_reviews
    f = reviewed; f.request_review()
    foreign = OrgContext(current_org_id=f.orgs[1], allowed_org_ids=f.orgs, is_root=True)
    with pytest.raises(HTTPException) as error:
        if action == 'request': f.request_review(context=foreign)
        elif action == 'review': f.review(context=foreign)
        else:
            with f.factory() as db:
                list_allocation_reviews(f.pool, f.payload.operation_key, page=1, limit=25, view='ALL',
                    db=db, context=foreign, user=SimpleNamespace(id=f.reviewer))
    assert error.value.status_code == 404


@pytest.mark.parametrize('same_key', [True, False])
def test_concurrent_decisions_have_one_effect(reviewed, same_key):
    f = reviewed; f.request_review(); barrier = Barrier(2)
    def decide(index):
        payload = f.decision if same_key or not index else f.decision.model_copy(update={'operation_key': uuid4(), 'outcome': 'REJECTED'})
        barrier.wait(timeout=10)
        try: return f.review(payload=payload).replayed
        except HTTPException as error: return error.status_code
    with ThreadPoolExecutor(max_workers=2) as executor: outcomes = list(executor.map(decide, range(2)))
    assert sorted(outcomes) == ([False, True] if same_key else [False, 409])
    with f.factory() as db:
        assert db.query(ManagerCaseDecision).filter_by(org_id=f.orgs[0]).count() == 1


def test_review_failure_rolls_back_decision_and_receipt(reviewed, monkeypatch):
    from importlib import import_module
    router = import_module('Routes.Inventory.CostPoolRouter')
    f = reviewed; f.request_review(); original = router.review_case
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('Synthetic failure before commit')
    monkeypatch.setattr(router, 'review_case', fail)
    with pytest.raises(RuntimeError): f.review()
    monkeypatch.setattr(router, 'review_case', original)
    assert not f.review().replayed

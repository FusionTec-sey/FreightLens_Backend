"""Separate PostgreSQL connections and real source services, synthetic data only."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4
import pytest
from Model.Credentials.users import User
from Model.containermgmt.Inventory.ProductPolicyDraft import ProductPolicyDraft
from Model.containermgmt.Orders.SalesIntent import SalesIntentRevision
from Schema.SalesIntentSchema import SalesIntentInput
from Services.customer_identity_service import create_customer
from Services.manager_case_service import request_case, review_case
from Services.policy_case_binding_service import load_policy_case_binding
from Services.policy_activation_service import activate_initial_policy
from Services.sales_intent_service import save_sales_intent
from Services.inventory_posting_service import PostingConflict
from tests.test_stock_ledger import stock  # noqa: F401
from tests.test_customer_identity import profile
from tests.test_inventory_policy_drafts import config


@pytest.fixture
def ready(stock):
    f = stock; f.document = uuid4(); customer_key = uuid4()
    with f.factory.begin() as db:
        reviewer = User(username='draft-review-' + uuid4().hex, password_hash='test-only', org_id=f.orgs[0])
        db.add(reviewer); db.flush(); reviewer_id = reviewer.id
        db.add(ProductPolicyDraft(org_id=f.orgs[0], product_id=f.products[0], version=1,
            config=config(), created_by=f.actor))
    load = lambda db: load_policy_case_binding(db, f.context, f.products[0])
    with f.factory.begin() as db: binding = load(db)
    case = uuid4(); guard = lambda db: None
    request_case(f.factory, f.context, f.actor, case, binding=binding,
        reason='Synthetic concurrency policy', load_binding=load, authorize=guard)
    review_case(f.factory, f.context, reviewer_id, uuid4(), case_key=case, binding=binding,
        expected_version=1, outcome='APPROVED', reason='Synthetic review', load_binding=load, authorize=guard)
    activate_initial_policy(f.factory, f.context, reviewer_id, uuid4(), case_key=case, binding=binding, authorize=guard)
    create_customer(f.factory, f.context, f.actor, customer_key, profile(), expected_version=0, authorize=guard)
    f.payload = SalesIntentInput(customer_key=customer_key, expected_customer_version=1,
        branch_id=f.branches[0], lines=[dict(line_key=uuid4(), product_id=f.products[0],
            expected_policy_version=1, quantity='2', unit='BOX')])
    f.save = lambda key, version=0: save_sales_intent(f.factory, f.context, f.actor, key,
        f.document, f.payload, expected_version=version, authorize=guard)
    return f


def test_simultaneous_same_operation_has_one_effect(ready):
    f = ready; key = uuid4(); barrier = Barrier(2)
    def run(_):
        barrier.wait(timeout=10)
        return f.save(key).replayed
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(run, range(2))) == [False, True]
    with f.factory() as db:
        assert db.query(SalesIntentRevision).filter_by(document_key=f.document).count() == 1


@pytest.mark.parametrize('version', [0, 1])
def test_competing_new_or_revised_documents_have_one_version_winner(ready, version):
    f = ready
    if version: f.save(uuid4())
    barrier = Barrier(2)
    def run(_):
        barrier.wait(timeout=10)
        try: return f.save(uuid4(), version).result['version']
        except PostingConflict: return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(run, range(2)))
    assert result.count('conflict') == 1 and result.count(version + 1) == 1
    with f.factory() as db:
        assert db.query(SalesIntentRevision).filter_by(document_key=f.document).count() == version + 1

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4
from decimal import Decimal
import pytest
from Model.Credentials.users import User
from Model.containermgmt.Inventory.ProductPolicyDraft import ProductPolicyDraft
from Model.containermgmt.Inventory.ProductPolicyActivation import ProductPolicyActivation
from Model.containermgmt.Inventory.ManagerCase import ManagerCaseUse
from Schema.InventoryPolicySchema import InventoryPolicyConfig
from Services.manager_case_service import request_case, review_case
from Services.policy_case_binding_service import load_policy_case_binding
from Services.policy_activation_service import activate_initial_policy
from Services.inventory_posting_service import PostingConflict
from tests.test_stock_ledger import stock  # noqa: F401


@pytest.fixture
def reviewed(stock):
    f = stock
    f.policy = InventoryPolicyConfig(base_unit="PCS", quantity_step="0.000001", tracking="UNTRACKED")
    with f.factory.begin() as db:
        reviewer = User(username="activate-" + uuid4().hex, password_hash="test-only", org_id=f.orgs[0])
        db.add(reviewer); db.flush(); f.reviewer = reviewer.id
        db.add(ProductPolicyDraft(org_id=f.orgs[0], product_id=f.products[0], version=1,
            config=f.policy.model_dump(mode="json"), created_by=f.actor))
    f.load = lambda db: load_policy_case_binding(db, f.context, f.products[0])
    with f.factory.begin() as db: f.binding = f.load(db)
    f.case = uuid4()
    request_case(f.factory, f.context, f.actor, f.case, binding=f.binding, reason="Synthetic request",
        load_binding=f.load, authorize=lambda db: None)
    review_case(f.factory, f.context, f.reviewer, uuid4(), case_key=f.case, binding=f.binding,
        expected_version=1, outcome="APPROVED", reason="Synthetic review", load_binding=f.load, authorize=lambda db: None)
    f.activate = lambda key=None, factory=None: activate_initial_policy(factory or f.factory, f.context,
        f.actor, key or uuid4(), case_key=f.case, binding=f.binding, authorize=lambda db: None)
    return f


def test_concurrent_activation_has_one_effect(reviewed):
    f = reviewed; barrier = Barrier(2, timeout=10)
    def run(_):
        barrier.wait()
        try: f.activate(); return "activated"
        except PostingConflict: return "conflict"
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(run, range(2))) == ["activated", "conflict"]
    with f.factory() as db:
        assert db.query(ProductPolicyActivation).filter_by(org_id=f.orgs[0]).count() == 1
        assert db.query(ManagerCaseUse).filter_by(org_id=f.orgs[0]).count() == 1


def test_shared_transaction_rollback_restores_approval(reviewed):
    f = reviewed
    with pytest.raises(RuntimeError):
        with f.factory.begin() as db:
            f.activate(factory=db)
            raise RuntimeError("Synthetic downstream failure")
    with f.factory() as db:
        assert db.query(ProductPolicyActivation).filter_by(org_id=f.orgs[0]).count() == 0
        assert db.query(ManagerCaseUse).filter_by(org_id=f.orgs[0]).count() == 0
    assert f.activate().result["status"] == "ACTIVE"


def test_existing_stock_cannot_be_silently_reclassified(reviewed):
    f = reviewed; f.open()
    with pytest.raises(PostingConflict, match="stock history"):
        f.activate()
    with f.factory() as db:
        assert db.query(ManagerCaseUse).filter_by(org_id=f.orgs[0]).count() == 0


def test_opening_cannot_override_active_policy(reviewed):
    f = reviewed; f.activate()
    other = InventoryPolicyConfig(base_unit="PCS", quantity_step="1", tracking="UNTRACKED")
    with pytest.raises(PostingConflict, match="reviewed active policy"):
        f.open(policy=other)
    assert Decimal(f.open(policy=f.policy).result["on_hand"]) == 10


def test_racing_opening_and_activation_never_reinterpret_stock(reviewed):
    f = reviewed; barrier = Barrier(2, timeout=10)
    def activate():
        barrier.wait()
        try: f.activate(); return "activated"
        except PostingConflict: return "blocked"
    def opening():
        barrier.wait()
        return f.open(policy=f.policy)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = executor.submit(activate), executor.submit(opening)
        assert first.result() in ("activated", "blocked")
        assert Decimal(second.result().result["on_hand"]) == 10

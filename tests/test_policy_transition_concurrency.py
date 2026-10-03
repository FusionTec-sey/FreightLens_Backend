from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4
import pytest
from Model.containermgmt.Inventory.ProductPolicyDraft import ProductPolicyDraft
from Model.containermgmt.Inventory.ProductPolicyActivation import ProductPolicyActivation
from Model.containermgmt.Inventory.ManagerCase import ManagerCaseUse
from Schema.InventoryPolicySchema import InventoryPolicyConfig
from Services.manager_case_service import request_case, review_case
from Services.policy_activation_service import activate_initial_policy
from Services.inventory_posting_service import PostingConflict
from tests.test_policy_activation_concurrency import reviewed  # noqa: F401
from tests.test_stock_ledger import stock  # noqa: F401


@pytest.fixture
def revision(reviewed):
    f = reviewed; f.activate()
    f.new_policy = InventoryPolicyConfig(base_unit="PCS", quantity_step="1", tracking="UNTRACKED")
    with f.factory.begin() as db:
        db.add(ProductPolicyDraft(org_id=f.orgs[0], product_id=f.products[0], version=2,
            config=f.new_policy.model_dump(mode="json"), created_by=f.actor))
    with f.factory.begin() as db: f.revision_binding = f.load(db)
    f.revision_case = uuid4()
    request_case(f.factory, f.context, f.actor, f.revision_case, binding=f.revision_binding,
        reason="Synthetic revision", load_binding=f.load, authorize=lambda db: None)
    review_case(f.factory, f.context, f.reviewer, uuid4(), case_key=f.revision_case,
        binding=f.revision_binding, expected_version=1, outcome="APPROVED", reason="Synthetic review",
        load_binding=f.load, authorize=lambda db: None)
    f.revise = lambda key=None, factory=None: activate_initial_policy(factory or f.factory, f.context,
        f.actor, key or uuid4(), case_key=f.revision_case, binding=f.revision_binding,
        expected_active_version=1, authorize=lambda db: None)
    return f


@pytest.mark.parametrize("same_key", [False, True])
def test_competing_revisions_have_one_effect(revision, same_key):
    f = revision; barrier = Barrier(2, timeout=10); key = uuid4()
    def run(index):
        barrier.wait()
        try: return "replayed" if f.revise(key if same_key or not index else uuid4()).replayed else "posted"
        except PostingConflict: return "conflict"
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(run, range(2))) == sorted(["posted", "replayed" if same_key else "conflict"])
    with f.factory() as db:
        assert db.query(ProductPolicyActivation).filter_by(org_id=f.orgs[0]).count() == 2
        assert db.query(ManagerCaseUse).filter_by(org_id=f.orgs[0]).count() == 2


def test_revision_rollback_preserves_approval_and_predecessor(revision):
    f = revision; key = uuid4()
    with pytest.raises(RuntimeError):
        with f.factory.begin() as db:
            f.revise(key, factory=db)
            raise RuntimeError("Synthetic downstream failure")
    with f.factory() as db:
        assert db.query(ProductPolicyActivation).filter_by(org_id=f.orgs[0]).count() == 1
        assert db.query(ManagerCaseUse).filter_by(org_id=f.orgs[0]).count() == 1
    assert f.revise(key).result["version"] == 2


def test_racing_stock_opening_and_revision_cannot_both_change_policy(revision):
    f = revision; barrier = Barrier(2, timeout=10)
    def revise():
        barrier.wait()
        try: f.revise(); return "revision"
        except PostingConflict: return "blocked"
    def open_stock():
        barrier.wait()
        try: f.open(policy=f.policy); return "opening"
        except PostingConflict: return "blocked"
    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = executor.submit(revise), executor.submit(open_stock)
        assert (first.result(), second.result()) in [("revision", "blocked"), ("blocked", "opening")]


def test_even_zero_stock_history_requires_real_transition(revision):
    from decimal import Decimal
    from Services.inventory_quantity_service import QuantityBreakdown
    f = revision
    f.open(policy=f.policy, quantities=QuantityBreakdown(Decimal("0")))
    with pytest.raises(PostingConflict, match="stock history"):
        f.revise()


def test_barcode_registration_race_cannot_leave_a_new_code_on_a_superseded_policy(revision):
    from Schema.UnitBarcodeSchema import UnitBarcodeCreate
    from Services.unit_barcode_service import register_barcode
    f = revision; barrier = Barrier(2, timeout=10)
    def revise():
        barrier.wait()
        try: f.revise(); return "revision"
        except PostingConflict: return "blocked"
    def barcode():
        barrier.wait()
        payload = UnitBarcodeCreate(operation_key=uuid4(), expected_policy_version=1, barcode="RACE-000", unit="PCS")
        try:
            register_barcode(f.factory, f.context, f.actor, product_id=f.products[0], payload=payload, authorize=lambda db: None)
            return "barcode"
        except PostingConflict: return "blocked"
    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = executor.submit(revise), executor.submit(barcode)
        assert (first.result(), second.result()) in [("revision", "blocked"), ("blocked", "barcode")]

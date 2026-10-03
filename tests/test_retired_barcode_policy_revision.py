from uuid import uuid4
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from Services.barcode_retirement_service import load_retirement_binding, retire_barcode
from Services.manager_case_service import request_case, review_case
from Services.policy_transition_service import no_history_blockers
from Services.inventory_posting_service import PostingConflict
from Services.inventory_quantity_service import QuantityBreakdown
from Services.unit_barcode_service import register_barcode
from Schema.UnitBarcodeSchema import UnitBarcodeCreate
from tests.test_unit_barcode_concurrency import registration
from tests.test_policy_transition_concurrency import revision  # noqa: F401
from tests.test_policy_activation_concurrency import reviewed  # noqa: F401
from tests.test_stock_ledger import stock  # noqa: F401


def retire(f, barcode_id, session=None):
    load = lambda db: load_retirement_binding(db, f.context, barcode_id)
    with f.factory.begin() as db:
        binding = load(db)
    case = uuid4()
    request_case(f.factory, f.context, f.actor, case, binding=binding, reason="Correct setup",
        load_binding=load, authorize=lambda db: None)
    review_case(f.factory, f.context, f.reviewer, uuid4(), case_key=case, binding=binding,
        expected_version=1, outcome="APPROVED", reason="Checked", load_binding=load, authorize=lambda db: None)
    return retire_barcode(session or f.factory, f.context, f.actor, uuid4(), case_key=case,
        binding=binding, authorize=lambda db: None)


def test_retired_codes_allow_reviewed_empty_revision_but_never_reuse(revision):
    f = revision
    old = registration(f)
    retire(f, old.result["id"])
    with f.factory() as db:
        assert no_history_blockers(db, f.context, f.products[0]) == []
    key = uuid4()
    assert f.revise(key).result["version"] == 2
    assert f.revise(key).replayed
    payload = UnitBarcodeCreate(operation_key=uuid4(), expected_policy_version=2, barcode="000-PCS", unit="PCS")
    with pytest.raises(PostingConflict):
        register_barcode(f.factory, f.context, f.actor, product_id=f.products[0], payload=payload, authorize=lambda db: None)
    replacement = payload.model_copy(update={"operation_key": uuid4(), "barcode": "NEW-PCS"})
    assert register_barcode(f.factory, f.context, f.actor, product_id=f.products[0], payload=replacement,
        authorize=lambda db: None).result["policy_version"] == 2


def test_one_live_code_still_blocks_after_other_code_retired(revision):
    f = revision
    retire(f, registration(f).result["id"])
    registration(f, code="STILL-LIVE")
    with pytest.raises(PostingConflict, match="barcodes"):
        f.revise()


def test_retirement_does_not_remove_zero_stock_history_blocker(revision):
    f = revision
    retire(f, registration(f).result["id"])
    f.open(policy=f.policy, quantities=QuantityBreakdown(Decimal("0")))
    with pytest.raises(PostingConflict, match="stock history"):
        f.revise()


def test_rolled_back_retirement_cannot_unlock_policy_revision(revision):
    f = revision
    barcode_id = registration(f).result["id"]
    with pytest.raises(RuntimeError):
        with f.factory.begin() as db:
            retire(f, barcode_id, session=db)
            raise RuntimeError("Synthetic rollback")
    with pytest.raises(PostingConflict, match="barcodes"):
        f.revise()


def test_replacement_registration_race_still_serializes_with_revision(revision):
    f = revision
    retire(f, registration(f).result["id"])
    barrier = Barrier(2, timeout=10)
    def revise():
        barrier.wait()
        try:
            f.revise()
            return "revision"
        except PostingConflict:
            return "blocked"
    def new_code():
        barrier.wait()
        try:
            registration(f, code="REPLACEMENT")
            return "registered"
        except PostingConflict:
            return "blocked"
    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = executor.submit(revise), executor.submit(new_code)
        assert (first.result(), second.result()) in [("revision", "blocked"), ("blocked", "registered")]


@pytest.mark.parametrize("with_stock", [False, True])
def test_retired_ancestor_does_not_block_later_compatible_extension(revision, with_stock):
    from Model.containermgmt.Inventory.ProductPolicyDraft import ProductPolicyDraft
    from Schema.InventoryPolicySchema import InventoryPolicyConfig
    from Services.policy_activation_service import activate_initial_policy, active_policy
    from Services.policy_transition_service import revision_blockers
    f = revision
    retire(f, registration(f).result["id"])
    f.revise()
    payload = UnitBarcodeCreate(operation_key=uuid4(), expected_policy_version=2,
        barcode="CURRENT-PCS", unit="PCS")
    register_barcode(f.factory, f.context, f.actor, product_id=f.products[0],
        payload=payload, authorize=lambda db: None)
    if with_stock:
        f.open(policy=f.new_policy)
    proposed = InventoryPolicyConfig.model_validate({**f.new_policy.model_dump(mode="json"),
        "conversions": [{"unit": "BOX", "factor": "2"}]})
    with f.factory.begin() as db:
        db.add(ProductPolicyDraft(org_id=f.orgs[0], product_id=f.products[0], version=3,
            config=proposed.model_dump(mode="json"), created_by=f.actor))
        db.flush()
        assert revision_blockers(db, f.context, f.products[0],
            active_policy(db, f.context, f.products[0]), proposed.model_dump(mode="json")) == []
        binding = f.load(db)
    case, operation = uuid4(), uuid4()
    request_case(f.factory, f.context, f.actor, case, binding=binding,
        reason="Add box after correction", load_binding=f.load, authorize=lambda db: None)
    review_case(f.factory, f.context, f.reviewer, uuid4(), case_key=case, binding=binding,
        expected_version=1, outcome="APPROVED", reason="Checked unchanged rules",
        load_binding=f.load, authorize=lambda db: None)
    def activate():
        return activate_initial_policy(f.factory, f.context, f.actor, operation,
            case_key=case, binding=binding, expected_active_version=2, authorize=lambda db: None)
    assert activate().result["version"] == 3
    assert activate().replayed
    with pytest.raises(PostingConflict, match="retired"):
        register_barcode(f.factory, f.context, f.actor, product_id=f.products[0],
            payload=payload.model_copy(update={"operation_key": uuid4(),
                "expected_policy_version": 3, "barcode": "000-PCS"}), authorize=lambda db: None)

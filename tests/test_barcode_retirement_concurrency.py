from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4
from dataclasses import replace
import pytest
from Services.barcode_retirement_service import load_retirement_binding, retire_barcode, retirements
from Services.manager_case_service import request_case, review_case
from Services.inventory_posting_service import PostingConflict
from tests.test_unit_barcode_concurrency import registration
from tests.test_policy_activation_concurrency import reviewed  # noqa: F401
from tests.test_stock_ledger import stock  # noqa: F401


@pytest.fixture
def retirement(reviewed):
    f = reviewed
    f.activate()
    barcode_id = registration(f).result["id"]
    load = lambda db: load_retirement_binding(db, f.context, barcode_id)
    with f.factory.begin() as db:
        binding = load(db)
    case = uuid4()
    request_case(f.factory, f.context, f.actor, case, binding=binding, reason="Incorrect code",
        load_binding=load, authorize=lambda db: None)
    review_case(f.factory, f.context, f.reviewer, uuid4(), case_key=case, binding=binding,
        expected_version=1, outcome="APPROVED", reason="Checked", load_binding=load, authorize=lambda db: None)
    f.retire = lambda key, factory=None, authorize=None, source=binding: retire_barcode(
        factory or f.factory, f.context, f.actor, key, case_key=case, binding=source,
        authorize=authorize or (lambda db: None))
    f.retirement_binding = binding
    return f


@pytest.mark.parametrize("same_key", [False, True])
def test_retirement_serializes_concurrent_requests(retirement, same_key):
    f = retirement
    barrier = Barrier(2, timeout=10)
    key = uuid4()
    def run(_):
        barrier.wait()
        try:
            return "replay" if f.retire(key if same_key else uuid4()).replayed else "retired"
        except PostingConflict:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(run, range(2))) == (["replay", "retired"] if same_key else ["conflict", "retired"])
    with f.factory() as db:
        assert retirements(db, f.context).count() == 1


def test_rollback_restores_retirement_approval(retirement):
    f = retirement
    key = uuid4()
    with pytest.raises(RuntimeError):
        with f.factory.begin() as db:
            f.retire(key, factory=db)
            raise RuntimeError("Synthetic downstream failure")
    with f.factory() as db:
        assert retirements(db, f.context).count() == 0
    assert not f.retire(key).replayed


def test_replay_rechecks_authorization_and_changed_binding(retirement):
    f = retirement
    key = uuid4()
    f.retire(key)
    def denied(db):
        raise PermissionError("Permission revoked")
    with pytest.raises(PermissionError):
        f.retire(key, authorize=denied)
    with pytest.raises(PostingConflict):
        f.retire(key, source=replace(f.retirement_binding, source_version=2))

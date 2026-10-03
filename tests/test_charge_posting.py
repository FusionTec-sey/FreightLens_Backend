from uuid import uuid4
from dataclasses import replace
import pytest
from Model.containermgmt.Inventory.Valuation import InventoryValuation
from Services.charge_posting_service import post_allocated_charge
from Services.cost_content_preparation_service import PreparedChargeContent
from Services.inventory_posting_service import PostingConflict
from tests.test_cost_content_reviews import content_review  # noqa: F401
from tests.test_cost_charge_reviews import charge_review, charge, allocation, valued, stock  # noqa: F401


@pytest.fixture
def posting(content_review):
    f = content_review
    f.key = uuid4()
    f.prepared = PreparedChargeContent(f.content_binding, tuple(f.content.items()))
    def post(**changes):
        params = dict(proposal_key=f.payload.operation_key, case_key=f.content_case,
            prepared=f.prepared, expected_versions={f.products[0]: 1}, authority_claim=f.central_claim, authorize=lambda db: None,
            require_central_authority=lambda db: None, load_allocation=f.load_allocation)
        factory = changes.pop('factory', f.factory)
        key = changes.pop('operation_key', f.key)
        params.update(changes)
        return post_allocated_charge(factory, f.context, f.actor, key, **params)
    f.post = post
    return f


def test_coordinator_posts_and_replays_exact_intent(posting):
    f = posting
    result = f.post()
    assert not result.replayed and f.post().replayed
    assert result.result['status'] == 'UNRECONCILED'
    with f.factory() as db:
        assert db.get(InventoryValuation, result.result['valuation_ids'][0]).kind == 'CHARGE'
    with pytest.raises(PostingConflict):
        f.post(expected_versions={f.products[0]: 2})


@pytest.mark.parametrize('guard', ['authorize', 'require_central_authority'])
@pytest.mark.parametrize('replay', [False, True])
def test_permissions_and_central_authority_required_on_every_attempt(posting, guard, replay):
    f = posting
    if replay: f.post()
    def deny(db): raise PermissionError('Synthetic revoked authority')
    with pytest.raises(PermissionError): f.post(**{guard: deny})
    if not replay: assert f.content_evidence()


def test_shared_transaction_rolls_back_all_effects(posting):
    f = posting
    with pytest.raises(RuntimeError):
        with f.factory.begin() as db:
            f.post(factory=db)
            raise RuntimeError('Synthetic downstream failure')
    assert f.content_evidence()
    assert not f.post().replayed


def test_stale_version_rolls_back_approval_and_charge(posting):
    f = posting
    with pytest.raises(PostingConflict): f.post(expected_versions={f.products[0]: 2})
    assert f.content_evidence()
    assert not f.post().replayed


def test_other_operation_cannot_consume_same_charge(posting):
    f = posting; f.post()
    with pytest.raises(PostingConflict): f.post(operation_key=uuid4())


def test_foreign_prepared_content_rejected(posting):
    f = posting
    with pytest.raises(PermissionError):
        f.post(prepared=replace(f.prepared, source=replace(f.prepared.source, org_id=f.orgs[1])))


def test_replaced_content_rejected_before_consumption(posting):
    f = posting
    changed = tuple((key, value.model_copy(update={'sha256': 'b' * 64})) for key, value in f.content.items())
    with pytest.raises(PostingConflict): f.post(prepared=replace(f.prepared, fingerprints=changed))
    assert f.content_evidence()


def test_concurrent_coordinator_requests_have_one_effect(posting):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    f = posting; barrier = Barrier(2)
    def run(_):
        barrier.wait(timeout=10)
        return f.post().replayed
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(run, range(2))) == [False, True]
    with f.factory() as db:
        assert db.query(InventoryValuation).filter_by(org_id=f.orgs[0], kind='CHARGE').count() == 1

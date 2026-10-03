from uuid import uuid4
import pytest
from Services.cost_charge_review_service import approved_charge_evidence, CHARGE_POSTING_KIND
from Services.cost_charge_use_service import consume_cost_charge
from Services.manager_case_service import consume_case
from Services.inventory_posting_service import execute_once, PostingEffect, PostingConflict
from tests.test_cost_content_reviews import content_review  # noqa: F401
from tests.test_cost_charge_reviews import charge_review, charge, allocation, valued, stock  # noqa: F401


@pytest.fixture
def replay(content_review):
    f = content_review; f.post_key = uuid4(); f.expected = f.content_evidence()
    def evidence(db, key=None, actor=None, content=None, authorize=lambda db: None):
        return approved_charge_evidence(db, f.context, f.content_case, f.payload.operation_key,
            authorize=authorize, load_allocation=f.load_allocation, document_content=content or f.content,
            replay_operation_key=key or f.post_key, replay_actor_id=actor or f.actor)
    def post(kind=CHARGE_POSTING_KIND, include_charge=True, fail=False):
        def apply(db):
            if include_charge:
                consume_cost_charge(db, f.context, f.actor, f.post_key, f.payload.operation_key, f.expected,
                    authorize=lambda db: None, load_evidence=lambda db: evidence(db))
            consume_case(db, f.context, f.actor, f.post_key, case_key=f.content_case,
                binding=f.content_binding, load_binding=f.content_load, authorize=lambda db: None)
            if fail: raise RuntimeError('Synthetic domain rollback')
            return PostingEffect({'synthetic': True}, {'kind': 'test.charge-case-composition'})
        return execute_once(f.factory, f.context, f.actor, f.post_key, kind,
            {'proposal_key': str(f.payload.operation_key)}, apply, authorize=lambda db: evidence(db))
    f.replay_evidence, f.post = evidence, post
    return f


def test_exact_operation_replays_without_second_consumption(replay):
    f = replay
    assert not f.post().replayed
    assert f.post().replayed
    with pytest.raises(PostingConflict): f.content_evidence()
    with f.factory.begin() as db:
        assert f.replay_evidence(db) == f.expected


@pytest.mark.parametrize('wrong', ['operation', 'actor'])
def test_other_operation_or_actor_cannot_reuse_consumed_case(replay, wrong):
    f = replay; f.post()
    with f.factory.begin() as db, pytest.raises(PostingConflict):
        f.replay_evidence(db, key=uuid4() if wrong == 'operation' else None,
            actor=f.reviewer if wrong == 'actor' else None)


@pytest.mark.parametrize('kind,include_charge', [('test.not-valuation', True), (CHARGE_POSTING_KIND, False)])
def test_receipt_alone_or_wrong_domain_cannot_authorize_retry(replay, kind, include_charge):
    f = replay; f.post(kind=kind, include_charge=include_charge)
    with f.factory.begin() as db, pytest.raises(PostingConflict): f.replay_evidence(db)


def test_failed_domain_effect_rolls_back_charge_and_case_together(replay):
    f = replay
    with pytest.raises(RuntimeError): f.post(fail=True)
    assert f.content_evidence() == f.expected
    assert not f.post().replayed
    assert f.post().replayed


def test_replay_still_checks_permissions_and_current_file_identity(replay):
    f = replay; f.post()
    def deny(db): raise PermissionError('revoked')
    with f.factory.begin() as db, pytest.raises(PermissionError): f.replay_evidence(db, authorize=deny)
    changed = {key: value.model_copy(update={'sha256': 'b' * 64}) for key, value in f.content.items()}
    with f.factory.begin() as db, pytest.raises(PostingConflict): f.replay_evidence(db, content=changed)


def test_concurrent_same_operation_has_one_effect(replay):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    f = replay; barrier = Barrier(2)
    def post():
        barrier.wait(timeout=10)
        return f.post().replayed
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: post(), range(2)))
    assert sorted(results) == [False, True]

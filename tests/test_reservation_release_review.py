from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from decimal import Decimal as D
from uuid import uuid4
import pytest
from Model.Credentials.users import User
from Model.containermgmt.Inventory.ManagerCase import ManagerCase, ManagerCaseUse
from Services.manager_case_service import request_case, review_case
from Services.reservation_release_service import load_release_binding
from Services.stock_ledger_service import release_stock
from Services.inventory_posting_service import PostingConflict
from tests.test_sales_reservation_sources import demand  # noqa: F401
from tests.test_sales_intent_concurrency import ready  # noqa: F401
from tests.test_stock_ledger import stock  # noqa: F401


@pytest.fixture
def release(demand):
    f = demand; f.hold(); f.case = uuid4(); f.release_operation = uuid4()
    f.load_release = lambda db: load_release_binding(db, f.context, f.reservation, D('5'), 'PCS')
    with f.factory.begin() as db:
        f.binding = f.load_release(db)
        user = User(org_id=f.orgs[0], username='release-review-' + uuid4().hex[:24], password_hash='test-only')
        db.add(user); db.flush(); f.reviewer = user.id
    request_case(f.factory, f.context, f.actor, f.case, binding=f.binding,
        reason='Synthetic customer request', load_binding=f.load_release, authorize=lambda db: None)
    def review(outcome='APPROVED', actor=None):
        return review_case(f.factory, f.context, actor or f.reviewer, uuid4(), case_key=f.case,
            binding=f.binding, expected_version=1, outcome=outcome, reason='Synthetic manager decision',
            load_binding=f.load_release, authorize=lambda db: None)
    f.review = review
    def apply(**kw):
        return release_stock(kw.pop('factory', f.factory), f.context, f.actor,
            kw.pop('operation', f.release_operation), balance_id=f.balance, reservation_key=f.reservation,
            source_line_key=f.source.stock_source_key(), quantity=kw.pop('quantity', D('5')), input_unit='PCS',
            reason='Synthetic approved release', authority=f.claim,
            authorize=kw.pop('authorize', lambda db: None), case_key=f.case, release_binding=f.binding)
    f.release = apply
    return f


def test_approved_release_consumes_case_and_replays_once(release):
    f = release; f.review()
    result = f.release()
    assert result.result['reservation_remaining'] == '15.000000'
    assert not result.replayed and f.release().replayed
    with f.factory() as db:
        case = db.query(ManagerCase).filter_by(org_id=f.orgs[0], case_key=f.case).one()
        assert db.query(ManagerCaseUse).filter_by(org_id=f.orgs[0], case_id=case.id).count() == 1


@pytest.mark.parametrize('outcome', [None, 'REJECTED'])
def test_requested_or_rejected_case_cannot_release(release, outcome):
    f = release
    if outcome: f.review(outcome)
    with pytest.raises(PermissionError): f.release()


def test_self_approval_and_changed_release_amount_are_denied(release):
    f = release
    with pytest.raises(PermissionError): f.review(actor=f.actor)
    f.review()
    with pytest.raises(PostingConflict): f.release(quantity=D('6'))


def test_approval_consumption_rolls_back_with_stock(release):
    f = release; f.review()
    with pytest.raises(RuntimeError):
        with f.factory.begin() as db:
            f.release(factory=db)
            raise RuntimeError('Synthetic transaction failure')
    assert not f.release().replayed


def test_case_cannot_be_consumed_twice_concurrently(release):
    f = release; f.review(); barrier = Barrier(2)
    def run(_):
        barrier.wait(timeout=10)
        try: f.release(operation=uuid4()); return 'released'
        except PostingConflict: return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(run, range(2))) == ['conflict', 'released']


def test_later_draft_revision_invalidates_review(release):
    f = release; f.review(); f.save(uuid4(), version=1)
    with pytest.raises(PostingConflict): f.release()


def test_revoked_permission_blocks_release_retry(release):
    f = release; f.review(); f.release()
    def deny(db): raise PermissionError('Denied')
    with pytest.raises(PermissionError): f.release(authorize=deny)

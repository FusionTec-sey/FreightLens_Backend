from datetime import timedelta
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from Model.containermgmt.Inventory.ReservationDeadline import ReservationDeadline
from Model.containermgmt.Inventory.StockLedger import StockReservation
from Services.reservation_deadline_service import load_deadline_binding, apply_reviewed_deadline
from Services.manager_case_service import request_case, review_case
from Services.inventory_posting_service import PostingConflict
from tests.test_reservation_release_review import release  # noqa: F401
from tests.test_sales_reservation_sources import demand  # noqa: F401
from tests.test_sales_intent_concurrency import ready  # noqa: F401
from tests.test_stock_ledger import stock  # noqa: F401


@pytest.fixture
def deadline(release):
    f = release; f.next_review = f.review_at + timedelta(days=3)
    f.deadline_case = uuid4(); f.deadline_operation = uuid4()
    f.load_deadline = lambda db: load_deadline_binding(db, f.context, f.reservation, f.next_review)
    with f.factory.begin() as db: f.deadline_binding = f.load_deadline(db)
    request_case(f.factory, f.context, f.actor, f.deadline_case, binding=f.deadline_binding,
        reason='Synthetic agreed follow-up', load_binding=f.load_deadline, authorize=lambda db: None)
    f.approve_deadline = lambda actor=None: review_case(f.factory, f.context, actor or f.reviewer, uuid4(),
        case_key=f.deadline_case, binding=f.deadline_binding, expected_version=1, outcome='APPROVED',
        reason='Synthetic agreed timeline', load_binding=f.load_deadline, authorize=lambda db: None)
    f.apply_deadline = lambda **kw: apply_reviewed_deadline(kw.get('factory', f.factory), f.context, f.actor,
        kw.get('operation', f.deadline_operation), case_key=f.deadline_case, binding=f.deadline_binding,
        authorize=kw.get('authorize', lambda db: None))
    return f


def test_reviewed_deadline_history_and_retry_do_not_release_stock(deadline):
    f = deadline; f.approve_deadline()
    assert not f.apply_deadline().replayed and f.apply_deadline().replayed
    with f.factory() as db:
        row = db.query(ReservationDeadline).filter_by(org_id=f.orgs[0], reservation_key=f.reservation).one()
        assert row.version == 1 and row.previous_review_at == f.review_at and row.review_at == f.next_review
        hold = db.query(StockReservation).filter_by(org_id=f.orgs[0], reservation_key=f.reservation).one()
        assert hold.released == 0 and hold.review_at == f.review_at


def test_unapproved_and_self_review_are_denied(deadline):
    with pytest.raises(PermissionError): deadline.apply_deadline()
    with pytest.raises(PermissionError): deadline.approve_deadline(actor=deadline.actor)


def test_reviewed_deadline_invalidates_previous_release_case(deadline):
    f = deadline; f.review(); f.approve_deadline(); f.apply_deadline()
    with pytest.raises(PostingConflict): f.release()


def test_release_invalidates_pending_deadline_case(deadline):
    f = deadline; f.approve_deadline(); f.review(); f.release()
    with pytest.raises(PostingConflict): f.apply_deadline()


def test_deadline_and_case_use_rollback_together(deadline):
    f = deadline; f.approve_deadline()
    with pytest.raises(RuntimeError):
        with f.factory.begin() as db:
            f.apply_deadline(factory=db)
            raise RuntimeError('Synthetic rollback')
    assert not f.apply_deadline().replayed


def test_concurrent_deadline_consumption_has_one_effect(deadline):
    f = deadline; f.approve_deadline(); barrier = Barrier(2)
    def run(_):
        barrier.wait(timeout=10)
        try: f.apply_deadline(operation=uuid4()); return 'applied'
        except (PostingConflict, ValueError): return 'denied'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(run, range(2))) == ['applied', 'denied']


def test_revoked_permission_and_foreign_company_fail_even_on_retry(deadline):
    f = deadline; f.approve_deadline(); f.apply_deadline()
    def deny(db): raise PermissionError('Denied')
    with pytest.raises(PermissionError): f.apply_deadline(authorize=deny)
    f.context.current_org_id = f.orgs[1]
    with pytest.raises(LookupError): f.apply_deadline()


def test_history_is_immutable_and_dates_require_explicit_forward_timezone(deadline):
    f = deadline; f.approve_deadline(); f.apply_deadline()
    with pytest.raises(DBAPIError):
        with f.factory.begin() as db:
            db.execute(text('UPDATE containermgmt.reservation_deadline_revisions SET version=99 WHERE org_id=:org'), {'org': f.orgs[0]})
    with f.factory.begin() as db:
        with pytest.raises(ValueError): load_deadline_binding(db, f.context, f.reservation, f.next_review.replace(tzinfo=None))
        with pytest.raises(ValueError): load_deadline_binding(db, f.context, f.reservation, f.review_at)


def test_deadline_migration_is_replayable(deadline, monkeypatch):
    from Utils import migrate_20261003_reservation_deadlines as migration
    monkeypatch.setattr(migration, 'engine', deadline.factory.kw['bind'])
    migration.ensure_reservation_deadlines_schema(); migration.ensure_reservation_deadlines_schema()

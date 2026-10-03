from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from decimal import Decimal as D
from threading import Barrier
from uuid import uuid4
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from Model.containermgmt.Inventory.ReservationReallocation import ReservationReallocation
from Model.containermgmt.Inventory.Location import InventoryBranch
from Model.containermgmt.Inventory.StockLedger import StockBalance, StockReservation, StockMovement
from Model.containermgmt.Inventory.PostingOperation import PostingOperation
from Schema.SalesReservationSchema import SalesDemandReference
from Services.customer_identity_service import create_customer
from Services.sales_intent_service import save_sales_intent
from Services.reservation_reallocation_service import load_reallocation_binding
from Services.stock_ledger_service import reallocate_reservation
from Services.manager_case_service import request_case, review_case
from Services.inventory_posting_service import PostingConflict
from tests.test_customer_identity import profile
from tests.test_reservation_release_review import release  # noqa: F401
from tests.test_sales_reservation_sources import demand  # noqa: F401
from tests.test_sales_intent_concurrency import ready  # noqa: F401
from tests.test_stock_ledger import stock  # noqa: F401


@pytest.fixture
def move(release, monkeypatch):
    f = release; f.target_document = uuid4(); customer = uuid4()
    from Utils import migrate_20261003_reservation_segments as migration
    monkeypatch.setattr(migration, 'engine', f.factory.kw['bind'])
    migration.ensure_reservation_segments_schema()
    create_customer(f.factory, f.context, f.actor, customer, profile(), expected_version=0, authorize=lambda db: None)
    payload = f.payload.model_copy(deep=True); payload.customer_key = customer; payload.lines[0].line_key = uuid4()
    save_sales_intent(f.factory, f.context, f.actor, uuid4(), f.target_document, payload, expected_version=0, authorize=lambda db: None)
    f.target = SalesDemandReference(document_key=f.target_document, line_key=payload.lines[0].line_key, version=1)
    f.target_payload = payload; f.target_review = f.review_at+timedelta(days=1)
    f.move_case = uuid4(); f.move_operation = uuid4()
    f.load_move = lambda db: load_reallocation_binding(db, f.context, f.reservation, f.target, D('5'), f.target_review)
    with f.factory.begin() as db: f.move_binding = f.load_move(db)
    request_case(f.factory, f.context, f.actor, f.move_case, binding=f.move_binding,
        reason='Synthetic customer-interaction reallocation request', load_binding=f.load_move, authorize=lambda db: None)
    f.approve_move = lambda actor=None: review_case(f.factory, f.context, actor or f.reviewer, uuid4(), case_key=f.move_case,
        binding=f.move_binding, expected_version=1, outcome='APPROVED', reason='Synthetic independent decision', load_binding=f.load_move, authorize=lambda db: None)
    f.move = lambda **kw: reallocate_reservation(kw.get('factory', f.factory), f.context, f.actor, kw.get('operation', f.move_operation),
        case_key=f.move_case, binding=kw.get('binding', f.move_binding), business_date=date(2026, 10, 3), reason='Synthetic approved reallocation',
        authority=kw.get('authority', f.claim), authorize=kw.get('authorize', lambda db: None))
    return f


def test_reallocation_preserves_total_and_links_paired_immutable_movements(move):
    f = move; f.approve_move(); result = f.move()
    assert result.result['source_remaining'] == '15.000000'
    assert result.result['target_remaining'] == '5.000000'
    assert not result.replayed and f.move().replayed
    with f.factory() as db:
        balance = db.get(StockBalance, f.balance)
        assert balance.on_hand == D('40') and balance.reserved == D('20')
        history = db.get(ReservationReallocation, f.move_operation)
        assert history.source_key == f.reservation
        rows = db.query(StockMovement).filter(StockMovement.org_id == f.orgs[0], StockMovement.operation_key.in_([history.release_operation, history.reserve_operation])).all()
        assert len(rows) == 2 and sum(row.reserved_delta for row in rows) == 0
        assert db.query(PostingOperation).filter(PostingOperation.org_id == f.orgs[0], PostingOperation.operation_key.in_([f.move_operation, history.release_operation, history.reserve_operation])).count() == 3


def test_missing_approval_and_self_review_denied(move):
    with pytest.raises(PermissionError): move.move()
    with pytest.raises(PermissionError): move.approve_move(actor=move.actor)


def test_failed_destination_reservation_rolls_back_source_case_and_child_receipt(move, monkeypatch):
    import Services.stock_ledger_service as ledger
    f = move; f.approve_move(); original = ledger.reserve_stock
    def fail(*args, **kwargs): raise RuntimeError('Synthetic destination failure')
    monkeypatch.setattr(ledger, 'reserve_stock', fail)
    with pytest.raises(RuntimeError): f.move()
    with f.factory() as db:
        assert db.query(StockReservation).filter_by(org_id=f.orgs[0], reservation_key=f.reservation).one().released == 0
        assert db.get(ReservationReallocation, f.move_operation) is None
    monkeypatch.setattr(ledger, 'reserve_stock', original)
    assert not f.move().replayed


def test_shared_transaction_failure_rolls_back_entire_reallocation(move):
    f = move; f.approve_move()
    with pytest.raises(RuntimeError):
        with f.factory.begin() as db:
            f.move(factory=db); raise RuntimeError('Synthetic outer failure')
    assert not f.move().replayed


def test_competing_reallocation_requests_cannot_spend_same_approval(move):
    f = move; f.approve_move(); barrier = Barrier(2)
    def run(_):
        barrier.wait(timeout=10)
        try: f.move(operation=uuid4()); return 'moved'
        except PostingConflict: return 'denied'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(run, range(2))) == ['denied', 'moved']


def test_concurrent_identical_retry_has_one_effect(move):
    f = move; f.approve_move(); barrier = Barrier(2)
    def run(_):
        barrier.wait(timeout=10)
        return f.move().replayed
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(run, range(2))) == [False, True]


def test_target_changed_after_posting_denies_historical_replay(move):
    f = move; f.approve_move(); f.move()
    save_sales_intent(f.factory, f.context, f.actor, uuid4(), f.target_document, f.target_payload,
        expected_version=1, authorize=lambda db: None)
    with pytest.raises(PostingConflict): f.move()


def test_foreign_company_context_cannot_reuse_approval_or_receipt(move):
    f = move; f.approve_move(); f.move()
    f.context.current_org_id = f.orgs[1]
    with pytest.raises((LookupError, PermissionError, ValueError)): f.move()


def test_changed_target_and_source_release_invalidate_reallocation(move):
    f = move; f.approve_move(); f.review(); f.release()
    with pytest.raises(PostingConflict): f.move()


def test_target_revision_change_requires_new_review(move):
    f = move; f.approve_move()
    save_sales_intent(f.factory, f.context, f.actor, uuid4(), f.target_document, f.target_payload, expected_version=1, authorize=lambda db: None)
    with pytest.raises(PostingConflict): f.move()


def test_foreign_target_wrong_branch_and_cap_are_denied(move):
    f = move
    with f.factory.begin() as db:
        with pytest.raises(LookupError): load_reallocation_binding(db, f.context, f.reservation,
            f.target.model_copy(update={'document_key': uuid4()}), D('5'), f.target_review)
        with pytest.raises(PostingConflict): load_reallocation_binding(db, f.context, f.reservation, f.target, D('21'), f.target_review)
    with f.factory.begin() as db:
        branch = InventoryBranch(org_id=f.orgs[0], code='OTHER_STORE', name='Synthetic other store', kind='STORE')
        db.add(branch); db.flush()
        f.target_payload.branch_id = branch.id
    save_sales_intent(f.factory, f.context, f.actor, uuid4(), f.target_document, f.target_payload, expected_version=1, authorize=lambda db: None)
    with f.factory.begin() as db:
        with pytest.raises(PostingConflict, match='Another store'): load_reallocation_binding(db, f.context, f.reservation,
            f.target.model_copy(update={'version': 2}), D('5'), f.target_review)


def test_authority_and_permission_remain_required_on_replay(move):
    f = move; f.approve_move(); f.move()
    with pytest.raises(ValueError): f.move(authority=None)
    def deny(db): raise PermissionError('Denied')
    with pytest.raises(PermissionError): f.move(authorize=deny)


def test_reallocation_history_cannot_be_rewritten_and_migration_replays(move, monkeypatch):
    f = move; f.approve_move(); f.move()
    with pytest.raises(DBAPIError):
        with f.factory.begin() as db:
            db.execute(text('UPDATE containermgmt.reservation_reallocations SET quantity=1 WHERE operation_key=:key'), {'key': f.move_operation})
    from Utils import migrate_20261003_reservation_reallocations as migration
    monkeypatch.setattr(migration, 'engine', f.factory.kw['bind'])
    migration.ensure_reservation_reallocations_schema(); migration.ensure_reservation_reallocations_schema()

from datetime import date
from decimal import Decimal as D
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from Model.containermgmt.Inventory.StockLedger import StockReservation
from Services.stock_ledger_service import reserve_stock, reallocate_reservation
from Services.reservation_reallocation_service import load_reallocation_binding
from Services.manager_case_service import request_case, review_case
from Services.inventory_posting_service import PostingConflict
from Services.sales_reservation_source_service import active_demand_holds
from tests.test_reservation_reallocation import move  # noqa: F401
from tests.test_reservation_release_review import release  # noqa: F401
from tests.test_sales_reservation_sources import demand  # noqa: F401
from tests.test_sales_intent_concurrency import ready  # noqa: F401
from tests.test_stock_ledger import stock  # noqa: F401


def seed_target(f, quantity='6'):
    key = uuid4()
    reserve_stock(f.factory, f.context, f.actor, uuid4(), balance_id=f.balance, reservation_key=key,
        source_line_key=f.target.stock_source_key(), quantity=D(quantity), input_unit='PCS',
        review_at=f.review_at, reason='Synthetic existing customer hold', business_date=date(2026, 10, 3),
        authorize=lambda db: None, authority=f.claim, sales_source=f.target)
    return key


def renew(f):
    f.move_case = uuid4(); f.move_operation = uuid4()
    with f.factory.begin() as db: f.move_binding = f.load_move(db)
    request_case(f.factory, f.context, f.actor, f.move_case, binding=f.move_binding,
        reason='Synthetic exact supplemental allocation', load_binding=f.load_move, authorize=lambda db: None)
    f.approve_move()


def seed_other_location(f, quantity='6', different_batch=False):
    from Model.containermgmt.Inventory.Location import StockLocation
    from Model.containermgmt.Inventory.StockLedger import StockBalance, StockBatch
    from Schema.InventoryPolicySchema import InventoryPolicyConfig
    from Schema.InventoryBatchSchema import StockBatchIdentity
    from Services.stock_ledger_service import open_batch_stock
    from Services.inventory_quantity_service import QuantityBreakdown
    with f.factory.begin() as db:
        location = StockLocation(org_id=f.orgs[0], branch_id=f.branches[0], code='S'+uuid4().hex[:8].upper(), name='Synthetic second area', kind='SITE')
        db.add(location); db.flush(); location_id = location.id
        balance = db.get(StockBalance, f.balance); batch = db.get(StockBatch, balance.batch_key)
        policy = InventoryPolicyConfig.model_validate(balance.policy_config)
        identity = StockBatchIdentity(batch_key=uuid4() if different_batch else batch.batch_key,
            code='ALT'+uuid4().hex[:8] if different_batch else batch.code, shade=batch.shade, calibre=batch.calibre)
    opened = open_batch_stock(f.factory, f.context, f.actor, uuid4(), branch_id=f.branches[0], location_id=location_id,
        product_id=f.products[0], policy=policy, batch=identity, quantities=QuantityBreakdown(D('30')),
        reason='Synthetic second location', authority=f.claim, authorize=lambda db: None)
    key = uuid4()
    reserve_stock(f.factory, f.context, f.actor, uuid4(), balance_id=opened.result['balance_id'], reservation_key=key,
        source_line_key=f.target.stock_source_key(), quantity=D(quantity), input_unit='PCS', review_at=f.review_at,
        reason='Synthetic compatible split', business_date=date(2026,10,3), authority=f.claim,
        authorize=lambda db: None, sales_source=f.target)
    return key


def test_reviewed_supplement_preserves_compatible_multi_location_target(move):
    f = move; local = seed_target(f); other = seed_other_location(f); renew(f)
    result = f.move(); assert f.move().replayed
    with f.factory() as db:
        assert active_demand_holds(db, f.context, f.target_document)[f.target.line_key] == 17
        for key in (local, other):
            original = db.query(StockReservation).filter_by(reservation_key=key).one()
            assert original.quantity == 6 and original.released == 0 and original.review_at == f.review_at
        assert result.result['target_reservation_key'] not in (str(local), str(other))


def test_other_location_history_change_invalidates_approved_snapshot(move):
    f = move; seed_other_location(f); renew(f); seed_other_location(f, '1')
    with pytest.raises(PostingConflict, match='changed'): f.move()


def test_multi_location_combined_cap_is_enforced(move):
    f = move; seed_other_location(f, '20')
    with f.factory.begin() as db, pytest.raises(PostingConflict, match='Combined destination'):
        f.load_move(db)


def test_other_batch_target_is_not_mixed_by_review(move):
    f = move; seed_other_location(f, different_batch=True)
    with f.factory.begin() as db, pytest.raises(PostingConflict, match='same store, product and batch'):
        f.load_move(db)


def test_append_segment_preserves_original_and_combined_demand(move):
    f = move; original = seed_target(f); renew(f); result = f.move()
    assert f.move().replayed
    with f.factory() as db:
        hold = db.query(StockReservation).filter_by(reservation_key=original).one()
        assert hold.quantity == 6 and hold.released == 0 and hold.review_at == f.review_at
        assert active_demand_holds(db, f.context, f.target_document)[f.target.line_key] == 11
        assert result.result['target_reservation_key'] != str(original)
    renew(f); f.move()
    with f.factory() as db:
        assert active_demand_holds(db, f.context, f.target_document)[f.target.line_key] == 16
        assert db.query(StockReservation).filter_by(source_line_key=f.target.stock_source_key(), org_id=f.orgs[0]).count() == 3


def test_changed_destination_hold_invalidates_prior_review(move):
    f = move; f.approve_move(); seed_target(f)
    with pytest.raises(PostingConflict, match='changed'): f.move()


def test_combined_destination_cap_not_just_requested_quantity(move):
    f = move; seed_target(f, '20')
    with f.factory.begin() as db:
        with pytest.raises(PostingConflict, match='Combined destination'):
            load_reallocation_binding(db, f.context, f.reservation, f.target, D('5'), f.target_review)


def test_competing_approved_supplements_cannot_reuse_destination_snapshot(move):
    f = move; seed_target(f, '18'); renew(f)
    other = uuid4()
    request_case(f.factory, f.context, f.actor, other, binding=f.move_binding,
        reason='Synthetic competing request', load_binding=f.load_move, authorize=lambda db: None)
    review_case(f.factory, f.context, f.reviewer, uuid4(), case_key=other, binding=f.move_binding,
        expected_version=1, outcome='APPROVED', reason='Synthetic second review', load_binding=f.load_move, authorize=lambda db: None)
    barrier = Barrier(2)
    def run(case):
        barrier.wait(timeout=10)
        try:
            reallocate_reservation(f.factory, f.context, f.actor, uuid4(), case_key=case, binding=f.move_binding,
                business_date=date(2026, 10, 3), reason='Synthetic concurrent supplement', authority=f.claim, authorize=lambda db: None)
            return 'moved'
        except PostingConflict: return 'denied'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(run, [f.move_case, other])) == ['denied', 'moved']
    with f.factory() as db:
        assert active_demand_holds(db, f.context, f.target_document)[f.target.line_key] == 23


def test_changed_existing_deadline_requires_fresh_reallocation_review(move):
    from datetime import timedelta
    from Services.reservation_deadline_service import load_deadline_binding, apply_reviewed_deadline
    f = move; key = seed_target(f); renew(f)
    case = uuid4()
    load = lambda db: load_deadline_binding(db, f.context, key, f.review_at+timedelta(days=4))
    with f.factory.begin() as db: binding = load(db)
    request_case(f.factory, f.context, f.actor, case, binding=binding, reason='Synthetic revised follow-up', load_binding=load, authorize=lambda db: None)
    review_case(f.factory, f.context, f.reviewer, uuid4(), case_key=case, binding=binding,
        expected_version=1, outcome='APPROVED', reason='Synthetic reviewed date', load_binding=load, authorize=lambda db: None)
    apply_reviewed_deadline(f.factory, f.context, f.actor, uuid4(), case_key=case, binding=binding, authorize=lambda db: None)
    with pytest.raises(PostingConflict, match='changed'): f.move()


def test_generic_reserve_and_forged_parent_cannot_add_segments(move):
    f = move; seed_target(f)
    with pytest.raises(PostingConflict, match='already has'): seed_target(f, '1')
    with pytest.raises((PostingConflict, PermissionError)):
        reserve_stock(f.factory, f.context, f.actor, uuid4(), balance_id=f.balance, reservation_key=uuid4(),
            source_line_key=f.target.stock_source_key(), quantity=D('1'), input_unit='PCS', review_at=f.review_at,
            reason='Synthetic invalid bypass attempt', business_date=date(2026, 10, 3), authorize=lambda db: None,
            authority=f.claim, sales_source=f.target, reallocation_parent=uuid4())


def test_database_rejects_unreviewed_segment_and_historical_quantity_edit(move):
    f = move; key = seed_target(f)
    with pytest.raises(DBAPIError, match='Supplemental reservation'):
        with f.factory.begin() as db:
            db.add(StockReservation(org_id=f.orgs[0], balance_id=f.balance, reservation_key=uuid4(),
                source_line_key=f.target.stock_source_key(), quantity=D('1'), released=D('0'),
                review_at=f.review_at, created_by=f.actor))
    with pytest.raises(DBAPIError, match='immutable'):
        with f.factory.begin() as db:
            db.execute(text('UPDATE containermgmt.inventory_stock_reservations SET quantity=quantity+1 WHERE reservation_key=:key'), {'key': key})


def test_segments_migration_replays_without_changing_holds(move, monkeypatch):
    f = move; key = seed_target(f); renew(f); f.move()
    from Utils import migrate_20261003_reservation_segments as migration
    monkeypatch.setattr(migration, 'engine', f.factory.kw['bind'])
    migration.ensure_reservation_segments_schema(); migration.ensure_reservation_segments_schema()
    with f.factory() as db:
        assert db.query(StockReservation).filter_by(reservation_key=key).one().quantity == 6

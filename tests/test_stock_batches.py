"""Persisted lots use synthetic records in the guarded isolated database only."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal as D
from threading import Barrier
from uuid import uuid4
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from Schema.InventoryPolicySchema import InventoryPolicyConfig
from Schema.InventoryBatchSchema import StockBatchIdentity
from Services.stock_ledger_service import open_batch_stock
from Services.inventory_quantity_service import QuantityBreakdown
from Services.inventory_posting_service import PostingConflict
from Model.containermgmt.Inventory.StockLedger import StockBatch, StockBalance, StockMovement
from Model.containermgmt.Inventory.Location import StockLocation
from tests.test_stock_ledger import stock

TODAY = date(2026, 10, 2)


def policy(**changes):
    return InventoryPolicyConfig(**{"base_unit": "PCS", "tracking": "BATCH", "quantity_step": "1",
        "require_shade": True, "require_calibre": True, "require_expiry": True,
        "conversions": [{"unit": "BOX", "factor": "12"}], **changes})


def identity(**changes):
    return StockBatchIdentity(**{"batch_key": uuid4(), "code": uuid4().hex,
        "shade": "A", "calibre": "600", "expires_on": TODAY, **changes})


def opening(f, *, batch=None, rules=None, **changes):
    return open_batch_stock(f.factory, f.context, f.actor, changes.pop("key", uuid4()),
        **{"branch_id": f.branches[0], "location_id": f.locations[0], "product_id": f.products[0],
           "policy": rules or policy(), "batch": batch or identity(),
           "authority": f.claim, "authorize": lambda db: None,
           "quantities": QuantityBreakdown(D("10")), "reason": "Synthetic approved batch opening", **changes})


def second_site(f):
    with f.factory() as db:
        row = StockLocation(org_id=f.orgs[0], branch_id=f.branches[0], code="SECOND", name="Test second", kind="SITE")
        db.add(row); db.commit()
        return row.id


def test_multiple_lots_have_separate_quantities_and_exact_unit_holds(stock):
    f = stock
    lot = identity()
    key = uuid4()
    one = opening(f, batch=lot, key=key)
    assert opening(f, batch=lot, key=key).replayed
    two = opening(f, batch=identity(shade="B"))
    hold, source = uuid4(), uuid4()
    reserved = f.reserve(one.result["balance_id"], reservation_key=hold, source_line_key=source,
        quantity=D("0.5"), input_unit="BOX", business_date=TODAY)
    assert D(reserved.result["available"]) == 4 and reserved.result["batch_key"] == str(lot.batch_key)
    released = f.release(one.result["balance_id"], hold, source, quantity=D("0.25"), input_unit="BOX")
    assert D(released.result["reservation_remaining"]) == 3
    with f.factory() as db:
        assert db.get(StockBalance, two.result["balance_id"]).reserved == 0
        assert db.query(StockBatch).filter_by(org_id=f.orgs[0]).count() == 2


@pytest.mark.parametrize("field", ["shade", "calibre", "expires_on"])
def test_required_lot_attributes_cannot_be_omitted(stock, field):
    with pytest.raises(ValueError, match="required"):
        opening(stock, batch=identity(**{field: None}))
    with stock.factory() as db:
        assert db.query(StockBatch).filter_by(org_id=stock.orgs[0]).count() == 0


def test_expired_and_undated_requests_are_blocked_but_owned_release_remains_possible(stock):
    f = stock
    balance = opening(f).result["balance_id"]
    with pytest.raises(ValueError, match="business date"):
        f.reserve(balance)
    with pytest.raises(ValueError, match="Expired"):
        f.reserve(balance, business_date=date(2026, 10, 3))
    hold, source = uuid4(), uuid4()
    f.reserve(balance, reservation_key=hold, source_line_key=source, business_date=TODAY)
    assert D(f.release(balance, hold, source).result["reservation_remaining"]) == 4


def test_no_silent_mixed_batch_even_when_shade_matches(stock):
    f = stock
    balances = [opening(f).result["balance_id"] for _ in range(2)]
    source = uuid4()
    f.reserve(balances[0], source_line_key=source, business_date=TODAY)
    with pytest.raises(PostingConflict, match="approved request"):
        f.reserve(balances[1], source_line_key=source, business_date=TODAY)
    with f.factory() as db:
        assert db.get(StockBalance, balances[1]).reserved == 0


def test_simultaneous_different_lots_cannot_split_a_source_line(stock):
    f = stock
    balances = [opening(f).result["balance_id"] for _ in range(2)]
    source = uuid4()
    barrier = Barrier(2, timeout=10)
    def reserve(balance):
        barrier.wait()
        try:
            f.reserve(balance, source_line_key=source, business_date=TODAY)
            return "reserved"
        except PostingConflict:
            return "blocked"
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(reserve, balances)) == ["blocked", "reserved"]
    with f.factory() as db:
        assert sum(row.reserved for row in db.query(StockBalance).filter(StockBalance.id.in_(balances))) == 6


@pytest.mark.parametrize("same_key", [False, True])
def test_two_tills_cannot_oversell_a_batch_or_duplicate_a_retry(stock, same_key):
    f = stock
    balance = opening(f).result["balance_id"]
    first = (uuid4(), uuid4(), uuid4())
    intents = [first, first if same_key else (uuid4(), uuid4(), uuid4())]
    barrier = Barrier(2, timeout=10)
    def reserve(intent):
        key, hold, source = intent
        barrier.wait()
        try:
            return f.reserve(balance, key, reservation_key=hold, source_line_key=source, business_date=TODAY)
        except ValueError:
            return "insufficient"
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(reserve, intents))
    if same_key:
        assert sorted(result.replayed for result in results) == [False, True]
    else:
        assert results.count("insufficient") == 1
    with f.factory() as db:
        assert db.get(StockBalance, balance).reserved == 6
        assert db.query(StockMovement).filter_by(balance_id=balance).count() == 2


def test_same_lot_at_another_site_is_not_automatic_fulfilment(stock):
    f = stock
    lot = identity()
    first = opening(f, batch=lot).result["balance_id"]
    second = opening(f, batch=lot, location_id=second_site(f)).result["balance_id"]
    source = uuid4()
    f.reserve(first, source_line_key=source, business_date=TODAY)
    with pytest.raises(PostingConflict, match="multi-location"):
        f.reserve(second, source_line_key=source, business_date=TODAY)


def test_lot_identity_and_policy_cannot_change_when_opening_another_location(stock):
    f = stock
    lot = identity()
    opening(f, batch=lot)
    location = second_site(f)
    with pytest.raises(PostingConflict, match="identity"):
        opening(f, batch=lot.model_copy(update={"shade": "different"}), location_id=location)
    with pytest.raises(PostingConflict, match="transition"):
        opening(f, batch=lot, location_id=location, rules=policy(quantity_step="0.1"))
    with pytest.raises(PostingConflict, match="code"):
        opening(f, batch=identity(code=lot.code))
    with pytest.raises(PostingConflict, match="transition"):
        f.open()


@pytest.mark.parametrize("sql", [
    "UPDATE containermgmt.inventory_stock_batches SET shade='B' WHERE batch_key=:key",
    "DELETE FROM containermgmt.inventory_stock_batches WHERE batch_key=:key",
    "UPDATE containermgmt.inventory_stock_balances SET batch_key=NULL WHERE batch_key=:key",
])
def test_batch_history_is_immutable(stock, sql):
    f = stock
    lot = identity()
    opening(f, batch=lot)
    with f.factory() as db, pytest.raises(DBAPIError):
        db.execute(text(sql), {"key": lot.batch_key})
        db.commit()


def test_failed_opening_rolls_back_lot_balance_and_movement(stock, monkeypatch):
    f = stock
    import Services.stock_ledger_service as service
    def fail(*args, **kwargs):
        raise ValueError("Synthetic failure")
    monkeypatch.setattr(service, "_record", fail)
    with pytest.raises(ValueError, match="Synthetic"):
        opening(f)
    with f.factory() as db:
        for model in (StockBatch, StockBalance, StockMovement):
            assert db.query(model).filter_by(org_id=f.orgs[0]).count() == 0


def test_foreign_product_and_batch_references_fail_closed(stock):
    f = stock
    with pytest.raises(ValueError, match="scope"):
        opening(f, product_id=f.products[1])
    foreign = identity()
    with f.factory() as db:
        db.add(StockBatch(org_id=f.orgs[1], product_id=f.products[1], created_by=f.actor, **foreign.model_dump()))
        db.commit()
    with pytest.raises(DBAPIError):
        opening(f, batch=foreign)
    with f.factory() as db:
        assert db.query(StockBalance).filter_by(org_id=f.orgs[0]).count() == 0


def test_batch_migration_replays_without_changing_stock(stock, monkeypatch, test_engine):
    f = stock
    balance = opening(f).result["balance_id"]
    import Utils.migrate_20261002_stock_batches as migration
    monkeypatch.setattr(migration, "engine", test_engine)
    migration.ensure_stock_batches_schema(); migration.ensure_stock_batches_schema()
    with f.factory() as db:
        row = db.get(StockBalance, balance)
        assert row.on_hand == 10 and row.version == 1 and row.batch_key is not None

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal as D
from threading import Barrier
from uuid import uuid4
import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from Schema.InventorySerialSchema import SerialOpening, SerialOpeningItem
from Schema.InventoryPolicySchema import InventoryPolicyConfig
from Model.containermgmt.Inventory.StockSerial import StockSerialIdentity, StockSerialPosition
from Model.containermgmt.Inventory.StockLedger import StockBalance, StockReservation, StockMovement
from Services.stock_ledger_service import open_serial_stock
from Services.inventory_posting_service import PostingConflict
from tests.test_stock_ledger import stock
from tests.test_stock_batches import second_site


def rules():
    return InventoryPolicyConfig(base_unit="PCS", quantity_step="1", tracking="SERIAL")


def serials():
    return SerialOpening(items=[SerialOpeningItem(serial_key=uuid4(), serial_number="S-" + str(i), condition=condition)
        for i, condition in enumerate(["AVAILABLE", "AVAILABLE", "DAMAGED", "QUARANTINED"])])


def opening(f, registry=None, **changes):
    return open_serial_stock(f.factory, f.context, f.actor, changes.pop("key", uuid4()),
        **{"branch_id": f.branches[0], "location_id": f.locations[0], "product_id": f.products[0],
           "policy": rules(), "serials": registry or serials(), "reason": "Synthetic serial opening",
           "authority": f.claim, "authorize": lambda db: None, **changes})


def test_opening_counts_serials_and_reserves_quantity_without_assigning_identity(stock):
    f = stock
    rows = serials(); key = uuid4()
    opened = opening(f, rows, key=key)
    assert opening(f, SerialOpening(items=tuple(reversed(rows.items))), key=key).replayed
    balance = opened.result["balance_id"]
    assert D(opened.result["on_hand"]) == 4 and D(opened.result["available"]) == 2
    hold, source = uuid4(), uuid4()
    f.reserve(balance, quantity=D(2), reservation_key=hold, source_line_key=source)
    with pytest.raises(ValueError, match="Insufficient"):
        f.reserve(balance, quantity=D(1))
    with pytest.raises(ValueError, match="increment"):
        f.reserve(balance, quantity=D("0.5"))
    f.release(balance, hold, source, quantity=D(1))
    with f.factory() as db:
        positions = db.query(StockSerialPosition).filter_by(balance_id=balance).all()
        assert sorted(row.condition for row in positions) == ["AVAILABLE", "AVAILABLE", "DAMAGED", "QUARANTINED"]
        assert db.query(StockReservation).filter_by(balance_id=balance).one().quantity == 2
        assert db.get(StockBalance, balance).reserved == 1


@pytest.mark.parametrize("same_key", [False, True])
def test_concurrent_tills_cannot_oversell_or_duplicate_serial_quantity(stock, same_key):
    f = stock; balance = opening(f).result["balance_id"]
    intent = (uuid4(), uuid4(), uuid4())
    intents = [intent, intent if same_key else (uuid4(), uuid4(), uuid4())]
    barrier = Barrier(2, timeout=10)
    def run(args):
        key, hold, source = args; barrier.wait()
        try:
            return f.reserve(balance, key, quantity=D(2), reservation_key=hold, source_line_key=source)
        except ValueError:
            return "insufficient"
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(run, intents))
    if same_key:
        assert sorted(row.replayed for row in results) == [False, True]
    else:
        assert results.count("insufficient") == 1
    with f.factory() as db:
        assert db.get(StockBalance, balance).reserved == 2
        assert db.query(StockMovement).filter_by(balance_id=balance).count() == 2


def test_duplicate_serial_at_other_location_rolls_back(stock):
    f = stock
    opening(f)
    with pytest.raises(PostingConflict, match="already registered"):
        opening(f, location_id=second_site(f))
    with f.factory() as db:
        assert db.query(StockBalance).filter_by(org_id=f.orgs[0]).count() == 1
        assert db.query(StockSerialIdentity).filter_by(org_id=f.orgs[0]).count() == 4


def test_simultaneous_openings_cannot_register_same_serial_twice(stock):
    f = stock; locations = [f.locations[0], second_site(f)]
    registry = serials(); barrier = Barrier(2, timeout=10)
    def run(location):
        barrier.wait()
        try:
            opening(f, registry, location_id=location)
            return "opened"
        except PostingConflict:
            return "blocked"
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(run, locations)) == ["blocked", "opened"]


@pytest.mark.parametrize("change", ["number", "key", "blank", "control", "condition"])
def test_invalid_or_duplicate_identity_rejected(change):
    rows = serials().model_dump(mode="json")["items"]
    if change == "number": rows[1]["serial_number"] = rows[0]["serial_number"]
    elif change == "key": rows[1]["serial_key"] = rows[0]["serial_key"]
    elif change == "blank": rows[0]["serial_number"] = "  "
    elif change == "control": rows[0]["serial_number"] = "A\nB"
    else: rows[0]["condition"] = "RESERVED"
    with pytest.raises(ValidationError): SerialOpening(items=rows)


def test_mismatched_counts_fail_closed(stock):
    f = stock; balance = opening(f).result["balance_id"]
    with f.factory() as db:
        db.get(StockBalance, balance).on_hand = 5
        db.commit()
    with pytest.raises(ValueError, match="reconcile"):
        f.reserve(balance, quantity=D(1))


@pytest.mark.parametrize("sql", [
    "UPDATE containermgmt.inventory_stock_serial_identities SET serial_number='CHANGED' WHERE org_id=:org",
    "DELETE FROM containermgmt.inventory_stock_serial_identities WHERE org_id=:org",
    "UPDATE containermgmt.inventory_stock_serial_positions SET condition='DAMAGED' WHERE org_id=:org",
    "DELETE FROM containermgmt.inventory_stock_serial_positions WHERE org_id=:org",
])
def test_identity_and_unintegrated_position_changes_are_blocked(stock, sql):
    f = stock; opening(f)
    with f.factory() as db, pytest.raises(DBAPIError):
        db.execute(text(sql), {"org": f.orgs[0]}); db.commit()


def test_serial_opening_failure_rolls_back_every_record(stock, monkeypatch):
    f = stock
    import Services.stock_ledger_service as service
    def fail(*args, **kwargs): raise ValueError("Synthetic rollback")
    monkeypatch.setattr(service, "_record", fail)
    with pytest.raises(ValueError, match="Synthetic"):
        opening(f)
    with f.factory() as db:
        for model in (StockBalance, StockSerialIdentity, StockSerialPosition):
            assert db.query(model).filter_by(org_id=f.orgs[0]).count() == 0


def test_foreign_scope_and_migration_replay(stock, monkeypatch, test_engine):
    f = stock
    with pytest.raises(ValueError, match="scope"):
        opening(f, product_id=f.products[1])
    balance = opening(f).result["balance_id"]
    import Utils.migrate_20261002_stock_serials as migration
    monkeypatch.setattr(migration, "engine", test_engine)
    migration.ensure_stock_serials_schema(); migration.ensure_stock_serials_schema()
    with f.factory() as db:
        assert db.get(StockBalance, balance).on_hand == 4
        assert db.query(StockSerialPosition).filter_by(balance_id=balance).count() == 4


@pytest.mark.parametrize("ordinary", [True, False])
def test_sql_position_cannot_use_wrong_tracking_or_foreign_identity(stock, ordinary):
    f = stock
    balance = f.open().result["balance_id"] if ordinary else opening(f).result["balance_id"]
    with f.factory() as db:
        identity = StockSerialIdentity(org_id=f.orgs[1] if not ordinary else f.orgs[0],
            product_id=f.products[1] if not ordinary else f.products[0], serial_key=uuid4(),
            serial_number="SQL-GUARD", created_by=f.actor)
        db.add(identity); db.commit(); identity_id = identity.id
    with f.factory() as db, pytest.raises(DBAPIError):
        db.add(StockSerialPosition(org_id=f.orgs[0], product_id=f.products[0], serial_id=identity_id,
            balance_id=balance, condition="AVAILABLE", created_by=f.actor))
        db.commit()

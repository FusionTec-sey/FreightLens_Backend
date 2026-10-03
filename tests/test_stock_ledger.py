"""Committed synthetic rows in the dedicated test database, never preview stock."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from decimal import Decimal as D, localcontext
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

import Model
from Model.db import Base
from Model.Credentials.Organisation import Organisation
from Model.Credentials.users import User
from Model.containermgmt.Orders.Product import Product
from Model.containermgmt.Inventory.Location import InventoryBranch, StockLocation
from Model.containermgmt.Inventory.PostingOperation import PostingOperation
from Model.containermgmt.Inventory.StockLedger import StockBalance, StockReservation, StockMovement
from Services.inventory_quantity_service import QuantityBreakdown
from Services.inventory_posting_service import PostingConflict
from Services.stock_ledger_service import open_untracked_stock, reserve_stock, release_stock
from Utils.org_filter import OrgContext
from Schema.InventoryPolicySchema import InventoryPolicyConfig
from Model.containermgmt.Inventory.PostingAuthority import StoreNode, BranchAuthorityEpoch
from Services.posting_authority_service import AuthorityClaim


@pytest.fixture
def stock(test_engine):
    with test_engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS usercredentials"))
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS containermgmt"))
        Base.metadata.create_all(conn)
    key = uuid4().hex
    with Session(test_engine) as db:
        orgs = [Organisation(name="Stock " + key + str(i)) for i in range(2)]
        db.add_all(orgs); db.flush()
        user = User(username="stock-" + key, password_hash="test-only", org_id=orgs[0].id)
        db.add(user)
        branches = [InventoryBranch(org_id=o.id, code="TEST", name="Test", kind="STORE") for o in orgs]
        products = [Product(org_id=o.id, sku="TEST", name="Test", unit="PCS") for o in orgs]
        db.add_all(branches + products); db.flush()
        locations = [StockLocation(org_id=o.id, branch_id=b.id, code="TEST", name="Test", kind="SITE")
                     for o, b in zip(orgs, branches)]
        db.add_all(locations); db.commit()
        f = SimpleNamespace(factory=sessionmaker(test_engine), actor=user.id,
            orgs=[o.id for o in orgs], products=[p.id for p in products],
            branches=[b.id for b in branches], locations=[l.id for l in locations])
    f.context = OrgContext(current_org_id=f.orgs[0], allowed_org_ids=f.orgs, is_root=True)
    f.node_key = uuid4()
    with f.factory.begin() as db:
        node = StoreNode(org_id=f.orgs[0], node_key=f.node_key, created_by=f.actor)
        db.add(node); db.flush()
        f.node_id = node.id
        db.add(BranchAuthorityEpoch(org_id=f.orgs[0], branch_id=f.branches[0], node_id=node.id,
            epoch=1, state="ACTIVE", reason="Synthetic test authority", created_by=f.actor))
    f.claim = AuthorityClaim(f.orgs[0], f.branches[0], f.node_key, 1)
    f.open = lambda key=None, **kw: open_untracked_stock(f.factory, f.context, f.actor, key or uuid4(),
        authority=kw.pop("authority", f.claim), authorize=kw.pop("authorize", lambda db: None),
        branch_id=kw.pop("branch_id", f.branches[0]), location_id=kw.pop("location_id", f.locations[0]),
        product_id=kw.pop("product_id", f.products[0]), base_unit=kw.pop("base_unit", "PCS"),
        tracking_policy=kw.pop("tracking_policy", "UNTRACKED"), reason="Synthetic approved opening",
        policy=kw.pop("policy", InventoryPolicyConfig(base_unit="PCS", quantity_step="0.000001", tracking="UNTRACKED")),
        quantities=kw.pop("quantities", QuantityBreakdown(D("10"), damaged=D("1"), quarantined=D("1"))), **kw)
    f.review_at = datetime.now(timezone.utc) + timedelta(days=2)
    f.reserve = lambda balance, key=None, **kw: reserve_stock(f.factory, kw.pop("context", f.context),
        f.actor, key or uuid4(), balance_id=balance, reservation_key=kw.pop("reservation_key", uuid4()),
        authority=kw.pop("authority", f.claim), authorize=kw.pop("authorize", lambda db: None),
        source_line_key=kw.pop("source_line_key", uuid4()), quantity=kw.pop("quantity", D("6")),
        review_at=kw.pop("review_at", f.review_at), reason="Synthetic hold", **kw)
    f.release = lambda balance, hold, source, key=None, **kw: release_stock(f.factory, f.context,
        f.actor, key or uuid4(), balance_id=balance, reservation_key=hold, source_line_key=source,
        authority=kw.pop("authority", f.claim), authorize=kw.pop("authorize", lambda db: None),
        quantity=kw.pop("quantity", D("2")), reason="Synthetic approved release", **kw)
    return f


def test_persistent_breakdown_replay_and_reconciliation(stock):
    f = stock
    opening_key = uuid4()
    opened = f.open(opening_key)
    balance = opened.result["balance_id"]
    assert f.open(opening_key).replayed
    hold, source, key = uuid4(), uuid4(), uuid4()
    first = f.reserve(balance, key, reservation_key=hold, source_line_key=source)
    replay = f.reserve(balance, key, reservation_key=hold, source_line_key=source)
    assert replay.replayed and replay.result == first.result
    assert D(first.result["on_hand"]) == 10 and D(first.result["available"]) == 2
    release_key = uuid4()
    result = f.release(balance, hold, source, release_key)
    assert f.release(balance, hold, source, release_key).replayed
    assert D(result.result["reservation_remaining"]) == 4
    with f.factory() as db:
        row = db.get(StockBalance, balance)
        movements = db.query(StockMovement).filter_by(balance_id=balance).order_by(StockMovement.version).all()
        assert [m.kind for m in movements] == ["OPENING", "RESERVE", "RELEASE"]
        assert sum(m.on_hand_delta for m in movements) == row.on_hand == 10
        assert sum(m.reserved_delta for m in movements) == row.reserved == 4
        assert movements[-1].version == row.version == 3
        assert movements[-1].damaged == row.damaged == 1
        assert movements[-1].quarantined == row.quarantined == 1
        assert db.get(Product, f.products[0]).current_stock == 0


@pytest.mark.parametrize("same_key", [False, True])
def test_real_concurrent_reservations_do_not_oversell(stock, same_key):
    f = stock
    balance = f.open().result["balance_id"]
    intent = (uuid4(), uuid4(), uuid4())
    intents = [intent, intent if same_key else (uuid4(), uuid4(), uuid4())]
    barrier = Barrier(2, timeout=10)
    def run(args):
        key, hold, source = args
        barrier.wait()
        try:
            return f.reserve(balance, key, reservation_key=hold, source_line_key=source)
        except ValueError:
            return "insufficient"
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(run, intents))
    if same_key:
        assert sorted(r.replayed for r in results) == [False, True]
    else:
        assert results.count("insufficient") == 1
    with f.factory() as db:
        assert db.get(StockBalance, balance).reserved == 6
        assert db.query(StockReservation).filter_by(balance_id=balance).count() == 1
        assert db.query(StockMovement).filter_by(balance_id=balance).count() == 2


def test_cannot_consume_another_sources_reservation_or_over_release(stock):
    f = stock
    balance = f.open().result["balance_id"]
    hold, source = uuid4(), uuid4()
    f.reserve(balance, reservation_key=hold, source_line_key=source, quantity=D("3"))
    f.reserve(balance, quantity=D("4"))
    with pytest.raises(ValueError, match="Owned reservation"):
        f.release(balance, hold, uuid4())
    with pytest.raises(ValueError, match="this reservation"):
        f.release(balance, hold, source, quantity=D("4"))
    with f.factory() as db:
        assert db.get(StockBalance, balance).reserved == 7
        assert db.query(StockMovement).filter_by(balance_id=balance).count() == 3


def test_distinct_keys_cannot_reopen_bucket_or_duplicate_source(stock):
    f = stock
    balance = f.open().result["balance_id"]
    with pytest.raises(PostingConflict):
        f.open()
    source = uuid4()
    f.reserve(balance, source_line_key=source, quantity=D("1"))
    with pytest.raises(PostingConflict):
        f.reserve(balance, source_line_key=source, quantity=D("1"))


@pytest.mark.parametrize("field", ["branch_id", "location_id", "product_id"])
def test_root_multi_org_still_cannot_mix_owners(stock, field):
    f = stock
    other = {"branch_id": f.branches[1], "location_id": f.locations[1], "product_id": f.products[1]}
    with pytest.raises((ValueError, PermissionError), match="scope"):
        f.open(**{field: other[field]})
    with f.factory() as db:
        assert db.query(PostingOperation).filter_by(org_id=f.orgs[0]).count() == 0


def test_foreign_active_org_cannot_reserve_or_get_replay(stock):
    f = stock
    balance = f.open().result["balance_id"]
    key, hold, source = uuid4(), uuid4(), uuid4()
    f.reserve(balance, key, reservation_key=hold, source_line_key=source)
    other = OrgContext(current_org_id=f.orgs[1], allowed_org_ids=f.orgs, is_root=True)
    with pytest.raises(ValueError, match="scope"):
        f.reserve(balance, key, reservation_key=hold, source_line_key=source, context=other)


@pytest.mark.parametrize("change", [{"base_unit": "BOX"}, {"tracking_policy": "BATCH"},
    {"quantities": QuantityBreakdown(D("10"), reserved=D("1"))}])
def test_opening_rejects_unsupported_or_ownerless_stock(stock, change):
    with pytest.raises(ValueError):
        stock.open(**change)


def test_expired_review_date_does_not_release_stock_and_naive_date_rejected(stock):
    f = stock
    balance = f.open().result["balance_id"]
    f.reserve(balance, review_at=datetime.now(timezone.utc) - timedelta(days=1))
    with pytest.raises(ValueError, match="timezone"):
        f.reserve(balance, review_at=datetime(2026, 1, 1))
    with pytest.raises(ValueError, match="Insufficient"):
        f.reserve(balance, quantity=D("3"))


def test_stock_math_ignores_process_decimal_precision(stock):
    f = stock
    balance = f.open().result["balance_id"]
    hold, source = uuid4(), uuid4()
    with localcontext() as ctx:
        ctx.prec = 2
        f.reserve(balance, reservation_key=hold, source_line_key=source, quantity=D("1.123456"))
        result = f.release(balance, hold, source, quantity=D("0.000001"))
    assert D(result.result["reservation_remaining"]) == D("1.123455")


@pytest.mark.parametrize("sql", [
    "UPDATE containermgmt.inventory_stock_movements SET reason = 'changed' WHERE balance_id = :id",
    "UPDATE containermgmt.inventory_stock_movements SET is_deleted = true WHERE balance_id = :id",
    "DELETE FROM containermgmt.inventory_stock_movements WHERE balance_id = :id",
    "UPDATE containermgmt.inventory_stock_balances SET reserved = 11 WHERE id = :id",
    "UPDATE containermgmt.inventory_stock_balances SET on_hand = 'NaN' WHERE id = :id",
])
def test_database_guards(stock, sql):
    balance = stock.open().result["balance_id"]
    with pytest.raises(DBAPIError):
        with stock.factory.begin() as db:
            db.execute(text(sql), {"id": balance})


def test_product_composite_fk_rejects_foreign_owner(stock):
    f = stock
    balance = f.open().result["balance_id"]
    with pytest.raises(DBAPIError):
        with f.factory.begin() as db:
            db.execute(text("UPDATE containermgmt.inventory_stock_balances SET product_id = :product WHERE id = :id"),
                       {"product": f.products[1], "id": balance})


def test_missing_operation_receipt_cannot_commit_movement(stock):
    f = stock
    balance = f.open().result["balance_id"]
    hold = uuid4()
    f.reserve(balance, reservation_key=hold)
    with f.factory() as db:
        reservation_id = db.query(StockReservation).filter_by(org_id=f.orgs[0], reservation_key=hold).one().id
    with pytest.raises(DBAPIError) as error:
        with f.factory.begin() as db:
            db.add(StockMovement(org_id=f.orgs[0], created_by=f.actor, balance_id=balance,
                reservation_id=reservation_id, operation_key=uuid4(), version=3, kind="RELEASE",
                reason="Invalid standalone movement", on_hand_delta=D("0"), reserved_delta=D("-1"),
                on_hand=D("10"), reserved=D("5"), damaged=D("1"), quarantined=D("1")))
            db.flush()  # Deferred receipt FK permits staging, but not committing without a receipt.
    assert error.value.orig.diag.constraint_name == "fk_stock_movement_operation"


def test_concurrent_releases_cannot_release_more_than_owned(stock):
    f = stock
    balance = f.open().result["balance_id"]
    hold, source = uuid4(), uuid4()
    f.reserve(balance, reservation_key=hold, source_line_key=source, quantity=D("3"))
    barrier = Barrier(2, timeout=10)
    def run(_):
        barrier.wait()
        try:
            return f.release(balance, hold, source)
        except ValueError:
            return "insufficient"
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(run, range(2)))
    assert results.count("insufficient") == 1
    with f.factory() as db:
        assert db.get(StockBalance, balance).reserved == 1
        assert db.query(StockMovement).filter_by(balance_id=balance).count() == 3


def test_other_location_stock_is_never_automatically_allocated(stock):
    f = stock
    balance = f.open().result["balance_id"]
    with f.factory.begin() as db:
        second = StockLocation(org_id=f.orgs[0], branch_id=f.branches[0], code="SECOND",
                               name="Other physical store", kind="SITE")
        db.add(second); db.flush()
        location_id = second.id
    other_balance = f.open(location_id=location_id).result["balance_id"]
    f.reserve(balance)
    with pytest.raises(ValueError, match="Insufficient"):
        f.reserve(balance, quantity=D("3"))
    with f.factory() as db:
        assert db.get(StockBalance, other_balance).reserved == 0


@pytest.mark.parametrize("model,field,value", [(Product, "status", "inactive"),
    (Product, "is_shared", True), (Product, "is_deleted", True),
    (InventoryBranch, "is_active", False), (StockLocation, "is_active", False)])
def test_inactive_or_shared_catalogue_cannot_be_reserved(stock, model, field, value):
    f = stock
    balance = f.open().result["balance_id"]
    ids = {Product: f.products[0], InventoryBranch: f.branches[0], StockLocation: f.locations[0]}
    with f.factory.begin() as db:
        setattr(db.get(model, ids[model]), field, value)
    with pytest.raises((ValueError, PermissionError), match="scope"):
        f.reserve(balance)


def test_failure_after_projection_update_rolls_back_everything(stock, monkeypatch):
    import Services.stock_ledger_service as service
    f = stock
    balance = f.open().result["balance_id"]
    record = service._record
    def broken(db, *args, **kwargs):
        record(db, *args, **kwargs)
        db.flush()
        raise RuntimeError("interrupted before receipt commit")
    monkeypatch.setattr(service, "_record", broken)
    with pytest.raises(RuntimeError):
        f.reserve(balance)
    with f.factory() as db:
        row = db.get(StockBalance, balance)
        assert row.reserved == 0 and row.version == 1
        assert db.query(StockReservation).filter_by(balance_id=balance).count() == 0
        assert db.query(StockMovement).filter_by(balance_id=balance).count() == 1
        assert db.query(PostingOperation).filter_by(org_id=f.orgs[0]).count() == 1


def test_migration_replay_retains_stock(stock, test_engine, monkeypatch):
    import Utils.migrate_20261002_stock_ledger as migration
    key = uuid4()
    stock.open(key)
    monkeypatch.setattr(migration, "engine", test_engine)
    migration.ensure_stock_ledger_schema()
    migration.ensure_stock_ledger_schema()
    assert stock.open(key).replayed

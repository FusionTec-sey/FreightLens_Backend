"""T09 pilot handover movement; synthetic isolated PostgreSQL only."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal as D
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from Model.containermgmt.Inventory.StockLedger import StockBalance, StockMovement, StockReservation
from Model.containermgmt.Inventory.StockSerial import StockSerialMovement
from Model.containermgmt.Inventory.CostPool import InventoryCostPool, BranchCostPool
from Model.containermgmt.Inventory.PostingAuthority import CostPoolAuthorityEpoch
from Model.containermgmt.Inventory.Valuation import InventoryValuation
from Schema.InventorySerialSchema import SerialOpening
from Services.inventory_handover_movement_service import handover_reserved_stock
from Services.inventory_posting_service import PostingConflict
from Services.inventory_valuation_service import record_opening_value
from Services.posting_authority_service import CostPoolAuthorityClaim
from tests.test_stock_ledger import stock  # noqa: F401
from tests.test_inventory_valuation import valued  # noqa: F401
from tests.test_stock_serials import opening as serial_opening, serials
from Utils.org_filter import OrgContext


@pytest.fixture
def reserved_value(valued):
    f = valued
    f.value()
    f.hold = uuid4(); f.source = uuid4()
    held = f.reserve(f.balance, reservation_key=f.hold,
        source_line_key=f.source, quantity=D("3"))
    f.stock_version = held.result["version"]
    f.operation = uuid4()
    def post(**changes):
        return handover_reserved_stock(
            changes.pop("factory", f.factory),
            changes.pop("context", f.context), f.actor,
            changes.pop("operation_key", f.operation),
            balance_id=changes.pop("balance_id", f.balance),
            reservation_key=changes.pop("reservation_key", f.hold),
            source_line_key=changes.pop("source_line_key", f.source),
            quantity=changes.pop("quantity", D("2")),
            input_unit=changes.pop("input_unit", "PCS"),
            expected_stock_version=changes.pop("expected_stock_version", f.stock_version),
            expected_valuation_version=changes.pop("expected_valuation_version", 1),
            reason=changes.pop("reason", "Synthetic verified collection handover"),
            stock_authority=changes.pop("stock_authority", f.claim),
            cost_authority=changes.pop("cost_authority", f.central_claim),
            authorize_stock=changes.pop("authorize_stock", lambda db: None),
            authorize_financial=changes.pop("authorize_financial", lambda db: None),
            **changes,
        )
    f.handover = post
    return f


def test_handover_consumes_owned_hold_and_matching_pool_value_once(reserved_value):
    f = reserved_value
    result = f.handover()
    assert result.result["handed_over"] == "2.000000"
    assert result.result["on_hand"] == "8.000000"
    assert result.result["reserved"] == "1.000000"
    assert result.result["reservation_remaining"] == "1.000000"
    assert result.result["issued_value_scr"] == "24.000000"
    assert result.result["pool_quantity"] == "8.000000"
    assert result.result["pool_value_scr"] == "96.000000"
    replay = f.handover()
    assert replay.replayed and replay.result == result.result
    with f.factory() as db:
        assert db.get(StockBalance, f.balance).version == 3
        hold = db.query(StockReservation).filter_by(
            org_id=f.orgs[0], reservation_key=f.hold).one()
        assert hold.released == D("2")
        assert db.query(StockMovement).filter_by(
            org_id=f.orgs[0], kind="HANDOVER").count() == 1
        issue = db.query(InventoryValuation).filter_by(
            org_id=f.orgs[0], kind="ISSUE").one()
        assert issue.quantity == D("2") and issue.goods_value_scr == D("24")


def test_handover_rechecks_permissions_and_rejects_changed_or_stale_intent(reserved_value):
    f = reserved_value
    f.handover()
    def deny(db):
        raise PermissionError("denied")
    with pytest.raises(PermissionError, match="denied"):
        f.handover(authorize_stock=deny)
    with pytest.raises(PostingConflict):
        f.handover(quantity=D("1"))
    with pytest.raises(PostingConflict, match="Stock version"):
        f.handover(operation_key=uuid4(), quantity=D("1"))


def test_foreign_active_company_cannot_handover_or_read_replay(reserved_value):
    f = reserved_value
    f.handover()
    foreign = OrgContext(current_org_id=f.orgs[1],
        allowed_org_ids=f.orgs, is_root=True)
    with pytest.raises((ValueError, PermissionError)):
        f.handover(context=foreign)


def test_handover_rejects_wrong_source_and_unvalued_or_unreconciled_stock(reserved_value):
    f = reserved_value
    with pytest.raises(ValueError, match="Owned reservation"):
        f.handover(source_line_key=uuid4())
    with f.factory.begin() as db:
        db.get(StockBalance, f.balance).on_hand = D("9")
    with pytest.raises(PostingConflict, match="Physical and valued"):
        f.handover()


def test_handover_outer_rollback_removes_stock_value_and_receipt(reserved_value):
    f = reserved_value
    with pytest.raises(RuntimeError):
        with f.factory.begin() as db:
            f.handover(factory=db)
            raise RuntimeError("downstream invoice failure")
    assert not f.handover().replayed


def test_competing_handovers_cannot_reuse_one_expected_stock_version(reserved_value):
    f = reserved_value
    barrier = Barrier(2, timeout=10)
    def run(key):
        barrier.wait()
        try:
            return f.handover(operation_key=key)
        except PostingConflict:
            return None
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(run, [uuid4(), uuid4()]))
    assert sum(result is not None for result in results) == 1
    with f.factory() as db:
        assert db.query(StockMovement).filter_by(
            org_id=f.orgs[0], kind="HANDOVER").count() == 1
        assert db.query(InventoryValuation).filter_by(
            org_id=f.orgs[0], kind="ISSUE").count() == 1


def test_issue_and_handover_rows_are_database_guarded(reserved_value):
    f = reserved_value
    result = f.handover()
    with f.factory() as db:
        valuation_id = result.result["valuation_id"]
    with pytest.raises(DBAPIError):
        with f.factory.begin() as db:
            db.execute(text("UPDATE containermgmt.inventory_valuations "
                "SET goods_value_scr=0 WHERE id=:id"), {"id": valuation_id})


def test_handover_migration_replay_preserves_history(reserved_value, monkeypatch):
    from Utils import migrate_20261005_stock_movements as migration
    f = reserved_value
    f.handover()
    monkeypatch.setattr(migration, "engine", f.factory.kw["bind"])
    migration.ensure_inventory_handover_schema()
    migration.ensure_inventory_handover_schema()
    assert f.handover().replayed


@pytest.fixture
def serial_reserved_value(stock):
    f = stock
    serial_payload = serials().model_dump(mode="python")
    serial_payload["items"][-1]["condition"] = "AVAILABLE"
    f.registry = SerialOpening.model_validate(serial_payload)
    opened = serial_opening(f, f.registry)
    f.balance = opened.result["balance_id"]
    with f.factory.begin() as db:
        pool = InventoryCostPool(org_id=f.orgs[0], code="SERIAL-T09",
            name="Synthetic serial pool", created_by=f.actor)
        db.add(pool); db.flush(); f.pool = pool.id
        db.add(BranchCostPool(org_id=f.orgs[0], branch_id=f.branches[0],
            cost_pool_id=pool.id, created_by=f.actor))
        db.add(CostPoolAuthorityEpoch(org_id=f.orgs[0], cost_pool_id=pool.id,
            node_id=f.node_id, epoch=1, state="ACTIVE",
            reason="Synthetic serial value authority", created_by=f.actor))
    f.central_claim = CostPoolAuthorityClaim(
        f.orgs[0], f.pool, f.node_key, 1)
    record_opening_value(f.factory, f.context, f.actor, uuid4(),
        balance_id=f.balance, expected_version=0,
        goods_value_scr=D("40"), additional_cost_scr=D("8"),
        reason="Synthetic serial opening cost",
        authority_claim=f.central_claim, authorize=lambda db: None)
    f.hold, f.source = uuid4(), uuid4()
    held = f.reserve(f.balance, reservation_key=f.hold,
        source_line_key=f.source, quantity=D("2"))
    f.stock_version = held.result["version"]
    f.operation = uuid4()
    available = tuple(
        row.serial_key for row in f.registry.items if row.condition == "AVAILABLE")
    f.available_serials = available[:2]
    f.extra_available_serial = available[2]
    f.damaged_serial = next(
        row.serial_key for row in f.registry.items if row.condition == "DAMAGED")

    def post(**changes):
        return handover_reserved_stock(
            changes.pop("factory", f.factory),
            changes.pop("context", f.context), f.actor,
            changes.pop("operation_key", f.operation),
            balance_id=f.balance, reservation_key=f.hold,
            source_line_key=f.source, quantity=changes.pop("quantity", D("2")),
            input_unit="PCS", expected_stock_version=f.stock_version,
            expected_valuation_version=1,
            reason="Synthetic exact serial handover",
            stock_authority=f.claim, cost_authority=f.central_claim,
            authorize_stock=lambda db: None,
            authorize_financial=lambda db: None,
            serial_keys=changes.pop("serial_keys", f.available_serials),
            **changes)
    f.serial_handover = post
    return f


def test_serial_handover_records_exact_immutable_identities_once(serial_reserved_value):
    f = serial_reserved_value
    result = f.serial_handover()
    assert result.result["handed_over"] == "2.000000"
    assert result.result["serial_keys"] == sorted(
        str(key) for key in f.available_serials)
    assert f.serial_handover(
        serial_keys=tuple(reversed(f.available_serials))).replayed
    with f.factory() as db:
        rows = db.query(StockSerialMovement).filter_by(
            org_id=f.orgs[0], operation_key=f.operation).all()
        assert len(rows) == 2
        assert {row.from_balance_id for row in rows} == {f.balance}
        assert {row.from_condition for row in rows} == {"AVAILABLE"}
        assert db.get(StockBalance, f.balance).on_hand == D("2")
        movement_id = rows[0].id
    with pytest.raises(DBAPIError):
        with f.factory.begin() as db:
            db.execute(text("UPDATE containermgmt.inventory_stock_serial_movements "
                "SET from_condition='DAMAGED' WHERE id=:id"),
                {"id": movement_id})


def test_serial_handover_rejects_late_extra_identity(serial_reserved_value):
    f = serial_reserved_value
    f.serial_handover()
    with pytest.raises(DBAPIError, match="exact stock quantity"):
        with f.factory.begin() as db:
            stock = db.query(StockMovement).filter_by(
                org_id=f.orgs[0], operation_key=f.operation,
                kind="HANDOVER").one()
            identity = db.execute(text("""SELECT identity.id
                FROM containermgmt.inventory_stock_serial_identities identity
                WHERE identity.org_id=:org AND identity.serial_key=:key"""),
                {"org": f.orgs[0], "key": f.extra_available_serial}).scalar_one()
            db.add(StockSerialMovement(org_id=f.orgs[0],
                operation_key=f.operation, stock_movement_id=stock.id,
                serial_id=identity, product_id=f.products[0],
                sequence=1, kind="HANDOVER", from_balance_id=f.balance,
                to_balance_id=None, from_condition="AVAILABLE",
                to_condition=None, created_by=f.actor))


def test_serial_handover_requires_exact_available_identity_set(serial_reserved_value):
    f = serial_reserved_value
    with pytest.raises(PostingConflict, match="one exact identity"):
        f.serial_handover(serial_keys=f.available_serials[:1])
    with pytest.raises(PostingConflict, match="available"):
        f.serial_handover(serial_keys=(f.available_serials[0], f.damaged_serial))
    f.serial_handover()
    with pytest.raises(PostingConflict):
        f.serial_handover(serial_keys=tuple(reversed(f.available_serials[:-1]))
            + (f.damaged_serial,))


def test_serial_handover_migration_replay_preserves_history(serial_reserved_value, monkeypatch):
    from Utils import migrate_20261005_stock_serial_handovers as migration
    f = serial_reserved_value
    f.serial_handover()
    monkeypatch.setattr(migration, "engine", f.factory.kw["bind"])
    migration.ensure_stock_serial_handover_schema()
    migration.ensure_stock_serial_handover_schema()
    assert f.serial_handover().replayed


def test_competing_serial_handovers_cannot_reuse_identities_or_version(serial_reserved_value):
    f = serial_reserved_value
    barrier = Barrier(2, timeout=10)

    def run(key):
        barrier.wait()
        try:
            return f.serial_handover(operation_key=key)
        except PostingConflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(run, [uuid4(), uuid4()]))
    assert sum(result is not None for result in results) == 1
    with f.factory() as db:
        assert db.query(StockSerialMovement).filter_by(
            org_id=f.orgs[0]).count() == 2
        assert db.query(StockMovement).filter_by(
            org_id=f.orgs[0], kind="HANDOVER").count() == 1


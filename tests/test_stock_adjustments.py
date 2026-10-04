"""Reviewed corrections use the ledger, exact cases and trusted authority."""
from decimal import Decimal as D
from uuid import uuid4

import pytest
from sqlalchemy.exc import DBAPIError

from Model.Credentials.users import User
from Model.containermgmt.Inventory.ManagerCase import ManagerCaseUse
from Model.containermgmt.Inventory.StockLedger import StockBalance, StockMovement
from Services.inventory_posting_service import PostingConflict
from Services.manager_case_service import request_case, review_case
from Services.stock_adjustment_service import (
    load_stock_adjustment_binding,
    reload_stock_adjustment_binding,
)
from Services.stock_ledger_service import adjust_stock_balance
from Utils.migrate_20261004_stock_adjustments import prepare_stock_adjustment_schema
from tests.test_stock_ledger import stock  # noqa: F401


@pytest.fixture
def adjustments(stock, test_engine):
    with test_engine.begin() as conn:
        prepare_stock_adjustment_schema(conn)
        prepare_stock_adjustment_schema(conn)
    f = stock
    with f.factory.begin() as db:
        reviewer = User(username="stock-review-" + uuid4().hex,
            password_hash="test-only", org_id=f.orgs[0])
        db.add(reviewer); db.flush()
        f.reviewer = reviewer.id
    f.balance = f.open().result["balance_id"]
    return f


def binding_for(f, on_hand="9", damaged="1", quarantined="1"):
    with f.factory.begin() as db:
        return load_stock_adjustment_binding(
            db, f.context, f.balance, D(on_hand), D(damaged), D(quarantined))


def approve(f, binding):
    case_key = uuid4()
    load = lambda db: reload_stock_adjustment_binding(db, f.context, binding)
    request_case(f.factory, f.context, f.actor, case_key,
        binding=binding, reason="Synthetic counted correction",
        load_binding=load, authorize=lambda db: None)
    review_case(f.factory, f.context, f.reviewer, uuid4(), case_key=case_key,
        binding=binding, expected_version=1, outcome="APPROVED",
        reason="Independent synthetic review", load_binding=load,
        authorize=lambda db: None)
    return case_key


def test_approved_adjustment_is_atomic_immutable_and_replay_safe(adjustments):
    f = adjustments
    binding = binding_for(f)
    case_key = approve(f, binding)
    operation_key = uuid4()
    first = adjust_stock_balance(f.factory, f.context, f.actor, operation_key,
        case_key=case_key, binding=binding, reason="Approved counted correction",
        authority=f.claim, authorize=lambda db: None)
    replay = adjust_stock_balance(f.factory, f.context, f.actor, operation_key,
        case_key=case_key, binding=binding, reason="Approved counted correction",
        authority=f.claim, authorize=lambda db: None)
    assert replay.replayed and replay.result == first.result
    assert first.result["on_hand"] == "9.000000"
    with f.factory() as db:
        balance = db.get(StockBalance, f.balance)
        movements = db.query(StockMovement).filter_by(
            balance_id=f.balance, kind="ADJUSTMENT").all()
        assert balance.on_hand == 9 and balance.reserved == 0
        assert len(movements) == 1 and movements[0].on_hand_delta == -1
        assert db.query(ManagerCaseUse).filter_by(operation_key=operation_key).count() == 1
        from Model.containermgmt.Orders.Product import Product
        assert db.get(Product, f.products[0]).current_stock == 0


def test_self_review_and_changed_source_are_rejected(adjustments):
    f = adjustments
    binding = binding_for(f)
    case_key = uuid4()
    load = lambda db: reload_stock_adjustment_binding(db, f.context, binding)
    request_case(f.factory, f.context, f.actor, case_key, binding=binding,
        reason="Synthetic request", load_binding=load, authorize=lambda db: None)
    with pytest.raises(PermissionError, match="own case"):
        review_case(f.factory, f.context, f.actor, uuid4(), case_key=case_key,
            binding=binding, expected_version=1, outcome="APPROVED", reason="No self review",
            load_binding=load, authorize=lambda db: None)
    f.reserve(f.balance, quantity=D("1"))
    with pytest.raises(PostingConflict, match="changed"):
        review_case(f.factory, f.context, f.reviewer, uuid4(), case_key=case_key,
            binding=binding, expected_version=1, outcome="APPROVED", reason="Stale review",
            load_binding=load, authorize=lambda db: None)


def test_target_cannot_consume_reservations_or_use_fraction_outside_policy(adjustments):
    f = adjustments
    f.reserve(f.balance, quantity=D("4"))
    with f.factory.begin() as db:
        with pytest.raises(ValueError, match="exceed physical stock"):
            load_stock_adjustment_binding(db, f.context, f.balance, D("5"), D("1"), D("1"))


def test_database_rejects_unreviewed_adjustment_movement(adjustments):
    f = adjustments
    with pytest.raises(DBAPIError), f.factory.begin() as db:
        balance = db.get(StockBalance, f.balance)
        db.add(StockMovement(org_id=f.orgs[0], balance_id=balance.id,
            operation_key=uuid4(), version=balance.version + 1, kind="ADJUSTMENT",
            reason="Bypass attempt", on_hand_delta=D("-1"), reserved_delta=D("0"),
            on_hand=D("9"), reserved=balance.reserved, damaged=balance.damaged,
            quarantined=balance.quarantined, created_by=f.actor))
        db.flush()


def test_foreign_context_cannot_load_adjustment_source(adjustments):
    f = adjustments
    other = f.context.model_copy(update={"current_org_id": f.orgs[1], "selected_org_id": f.orgs[1]})
    with f.factory.begin() as db:
        with pytest.raises(LookupError, match="not found"):
            load_stock_adjustment_binding(db, other, f.balance, D("9"), D("1"), D("1"))


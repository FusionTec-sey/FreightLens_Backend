"""Existing stock writers must not escape a caller's larger transaction."""
from decimal import Decimal
from uuid import uuid4

import pytest

from Model.containermgmt.Inventory.StockLedger import StockBalance, StockReservation, StockMovement
from Model.containermgmt.Inventory.PostingOperation import PostingOperation
from tests.test_stock_ledger import stock  # noqa: F401 - synthetic PostgreSQL fixture


@pytest.mark.parametrize("operation", ["opening", "reserve", "release"])
def test_stock_effects_join_outer_rollback(stock, operation):
    f = stock
    factory = f.factory
    balance = None if operation == "opening" else f.open().result["balance_id"]
    hold, source, key = uuid4(), uuid4(), uuid4()
    if operation == "release":
        f.reserve(balance, reservation_key=hold, source_line_key=source)
    with pytest.raises(RuntimeError, match="synthetic invoice failure"):
        with factory.begin() as db:
            f.factory = db
            try:
                if operation == "opening":
                    f.open(key, authorize=lambda db: None)
                elif operation == "reserve":
                    f.reserve(balance, key, reservation_key=hold, source_line_key=source,
                              authorize=lambda db: None)
                else:
                    f.release(balance, hold, source, key, authorize=lambda db: None)
                raise RuntimeError("synthetic invoice failure")
            finally:
                f.factory = factory
    with factory() as db:
        assert db.query(PostingOperation).filter_by(org_id=f.orgs[0], operation_key=key).count() == 0
        assert db.query(StockMovement).filter_by(org_id=f.orgs[0], operation_key=key).count() == 0
        if operation == "opening":
            assert db.query(StockBalance).filter_by(org_id=f.orgs[0]).count() == 0
        elif operation == "reserve":
            assert db.get(StockBalance, balance).reserved == 0
            assert db.query(StockReservation).filter_by(org_id=f.orgs[0]).count() == 0
        else:
            assert db.get(StockBalance, balance).reserved == Decimal("6")
            assert db.query(StockReservation).filter_by(reservation_key=hold).one().released == 0


def test_shared_stock_requires_guard_and_guard_also_applies_on_replay(stock):
    f = stock
    factory = f.factory
    key = uuid4()
    with factory() as db:
        db.begin()
        f.factory = db
        try:
            with pytest.raises(ValueError, match="authorization guard"):
                f.open(key, authorize=None)
        finally:
            f.factory = factory
    f.open(key)
    def deny(db):
        raise PermissionError("authority revoked")
    with pytest.raises(PermissionError, match="revoked"):
        f.open(key, authorize=deny)


@pytest.mark.parametrize("action", ["reserve", "release"])
def test_shared_session_refreshes_preloaded_balances_and_holds(stock, action):
    f = stock
    factory = f.factory
    balance = f.open().result["balance_id"]
    hold, source = uuid4(), uuid4()
    if action == "release":
        f.reserve(balance, reservation_key=hold, source_line_key=source)
    with factory() as db:
        db.begin()
        stale_balance = db.get(StockBalance, balance)
        if action == "release":
            stale_hold = db.query(StockReservation).filter_by(reservation_key=hold).one()
            f.release(balance, hold, source, quantity=Decimal("5"))
            assert stale_hold.released == 0
        else:
            f.reserve(balance)
            assert stale_balance.reserved == 0
        f.factory = db
        try:
            with pytest.raises(ValueError):
                if action == "release":
                    f.release(balance, hold, source, quantity=Decimal("2"))
                else:
                    f.reserve(balance, quantity=Decimal("3"))
        finally:
            f.factory = factory
    with factory() as db:
        assert db.get(StockBalance, balance).reserved == (1 if action == "release" else 6)

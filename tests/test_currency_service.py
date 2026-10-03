from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from Services.currency_service import CurrencyRateNotFound, to_base


class _Query:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *args):
        return self

    def order_by(self, *args):
        return self

    def first(self):
        return self.rows.pop(0) if self.rows else None


class _Db:
    def __init__(self, *rows):
        self.rows = list(rows)

    def query(self, model):
        if model.__name__ == "Organisation":
            return _Query([SimpleNamespace(base_currency="SCR")])
        return _Query(self.rows)


def test_to_base_prefers_direct_rate_and_rounds_money():
    db = _Db(SimpleNamespace(rate=Decimal("14.123456")))

    rate, amount, currency = to_base(db, 2, "USD", "10.125", date(2026, 10, 2))

    assert rate == Decimal("14.12345600")
    assert amount == Decimal("143.07")
    assert currency == "SCR"


def test_to_base_uses_one_for_base_currency():
    rate, amount, currency = to_base(_Db(), 2, "SCR", "15.555", date(2026, 10, 2))

    assert rate == Decimal("1.00000000")
    assert amount == Decimal("15.56")
    assert currency == "SCR"


def test_to_base_refuses_missing_exchange_rate():
    with pytest.raises(CurrencyRateNotFound):
        to_base(_Db(), 2, "EUR", 10, date(2026, 10, 2))

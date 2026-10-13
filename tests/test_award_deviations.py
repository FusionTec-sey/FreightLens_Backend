"""A vendor answering differently from the request must not slip through the award.

The case these came from: a line ordered 3, the vendor's minimum is 5. Before
this, the award copied the vendor's price and left the quantity at 3, so a quote
for $50 became an order for $30 and nobody was told until the invoice arrived.
"""
from types import SimpleNamespace

from Routes.Orders.QuoteComparisonService import QuoteComparisonService


def _line(item_id=1, qty=3, code=None, description="Tile 60x60"):
    return SimpleNamespace(
        id=item_id, quantity_ordered=qty, item_code=code, description=description
    )


def _quote_line(qty=3, substitute=False, availability="AVAILABLE", description="Tile 60x60"):
    return SimpleNamespace(
        quantity_quoted=qty, is_substitute=substitute,
        availability=availability, description=description, item_code=None,
        inventory_product_id=None,
    )


def test_an_exact_answer_is_not_a_deviation():
    assert QuoteComparisonService._deviation(_line(qty=3), _quote_line(qty=3)) is None


def test_a_minimum_order_quantity_is_a_deviation():
    dev = QuoteComparisonService._deviation(_line(qty=3), _quote_line(qty=5))

    assert dev is not None
    assert "quantity" in dev["kinds"]
    assert dev["quantity_requested"] == 3.0
    assert dev["quantity_quoted"] == 5.0


def test_a_substitute_is_a_deviation_even_at_the_requested_quantity():
    dev = QuoteComparisonService._deviation(
        _line(qty=10), _quote_line(qty=10, substitute=True, description="Equivalent tile")
    )

    assert dev is not None
    assert "substitute" in dev["kinds"]
    assert dev["substitute_description"] == "Equivalent tile"


def test_partial_availability_is_a_deviation():
    dev = QuoteComparisonService._deviation(
        _line(qty=10), _quote_line(qty=10, availability="PARTIAL")
    )

    assert dev is not None
    assert "partial" in dev["kinds"]


def test_a_quote_with_no_answer_for_the_line_is_not_a_deviation():
    assert QuoteComparisonService._deviation(_line(), None) is None


class _CountingQuery:
    """Enough of a SQLAlchemy query to count how many lookups were attempted."""

    def __init__(self, counter):
        self._counter = counter

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        self._counter.append(1)
        return None


class _CountingSession:
    def __init__(self):
        self.lookups = []

    def query(self, *args, **kwargs):
        return _CountingQuery(self.lookups)


def test_a_blank_item_code_never_falls_back_to_matching_by_code():
    """Blank codes matched every line of the quote, so line 2 took line 1's answer.

    The catalogue leaves item_code empty on most lines, and `item_code == ''`
    is true for all of them, so the fallback returned whichever row came first.
    With no code there is nothing to match on and the lookup has to stop.
    """
    session = _CountingSession()

    found = QuoteComparisonService._quote_item_for(
        session, SimpleNamespace(id=7), _line(item_id=7, code="   ")
    )

    assert found is None
    assert len(session.lookups) == 1, "only the po_item_id lookup may run for a blank code"


def test_a_real_item_code_still_falls_back():
    session = _CountingSession()

    QuoteComparisonService._quote_item_for(
        session, SimpleNamespace(id=7), _line(item_id=7, code="TL-6060")
    )

    assert len(session.lookups) == 2, "a quote typed without a link is still matched by code"

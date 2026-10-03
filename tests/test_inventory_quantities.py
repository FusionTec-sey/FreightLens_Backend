from dataclasses import FrozenInstanceError
from decimal import Decimal, localcontext
import pytest
from Services.inventory_quantity_service import QuantityBreakdown, LineFulfillment

D = Decimal


def test_availability_keeps_conditions_and_reservations_distinct():
    balance = QuantityBreakdown(D(20), reserved=D(4), damaged=D(3), quarantined=D(2))
    assert balance.available == D(11)
    reserved = balance.reserve(D(5))
    assert reserved.on_hand == D(20) and reserved.available == D(6)
    issued = reserved.handover_reserved(D(2))
    assert issued.on_hand == D(18) and issued.reserved == D(7) and issued.available == D(6)
    released = issued.release(D(3))
    assert released.on_hand == D(18) and released.available == D(9)
    assert balance.reserved == D(4)
    with pytest.raises(FrozenInstanceError):
        balance.on_hand = D(30)


@pytest.mark.parametrize("value", [D(-1), D("NaN"), D("Infinity"), D("0.0000001"),
                                   D("1000000000000"), 1.5, 2, True, "3"])
def test_invalid_quantity_is_rejected_not_clamped(value):
    with pytest.raises(ValueError):
        QuantityBreakdown(value)
    with pytest.raises(ValueError):
        LineFulfillment("line-a", D(4), pending_return=value)


def test_invalid_aggregate_is_not_silently_zeroed():
    with pytest.raises(ValueError):
        QuantityBreakdown(D(5), reserved=D(4), damaged=D(2))
    with pytest.raises(ValueError):
        QuantityBreakdown(D(5), damaged=D(3), quarantined=D(3))


@pytest.mark.parametrize("method,quantity", [("reserve", D(4)), ("reserve", D(0)),
    ("release", D(4)), ("release", D(0)), ("handover_reserved", D(4)), ("handover_reserved", D(0))])
def test_operations_never_take_unavailable_or_unreserved_stock(method, quantity):
    balance = QuantityBreakdown(D(8), reserved=D(3), damaged=D(2))
    with pytest.raises(ValueError):
        getattr(balance, method)(quantity)


def test_fulfillment_respects_actual_handover_and_pending_returns():
    row = LineFulfillment("original-line", D(10), handed_over=D(4), reserved=D(3),
                          cancelled_uncollected=D(1), returned=D(1), pending_return=D(1))
    assert row.outstanding_collection == D(5)
    assert row.unallocated == D(2)
    assert row.returnable == D(2)
    # An uncollected sale is cancellable, not a physical return.
    assert LineFulfillment("other-line", D(10)).returnable == D(0)


@pytest.mark.parametrize("fields", [dict(handed_over=D(6)), dict(reserved=D(6)),
    dict(handed_over=D(4), cancelled_uncollected=D(2)), dict(returned=D(1)),
    dict(handed_over=D(2), returned=D(1), pending_return=D(2))])
def test_fulfillment_rejects_over_collection_or_return(fields):
    with pytest.raises(ValueError):
        LineFulfillment("line-a", D(5), **fields)


def test_return_does_not_create_new_pickup_entitlement():
    row = LineFulfillment("line-a", D(5), handed_over=D(5), returned=D(5))
    assert row.outstanding_collection == row.returnable == D(0)


def test_decimal_results_do_not_depend_on_global_precision():
    with localcontext() as ctx:
        ctx.prec = 2
        row = QuantityBreakdown(D("123456.123456"), reserved=D("0.000001"))
        assert row.available == D("123456.123455")
        assert row.reserve(D("1.000001")).available == D("123455.123454")
        assert LineFulfillment("line-a", D("123456.123456"), handed_over=D("0.000001")).outstanding_collection == D("123456.123455")

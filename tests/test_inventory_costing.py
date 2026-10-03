from dataclasses import FrozenInstanceError
from decimal import Decimal as D, localcontext, ROUND_DOWN, Inexact
from random import Random

import pytest

from Services.inventory_costing_service import (
    CostPool, CostBalance, CostingError, MAX_QUANTITY, MAX_VALUE,
    receive, issue, dispatch_transfer, receive_transfer, allocate_additional_cost,
)

MAHE = CostPool(1, 10, 100)
PRASLIN = CostPool(1, 20, 100)


def test_explicit_pool_identity_is_not_a_branch_id():
    from Services.inventory_costing_service import COSTING_POLICY_VERSION
    assert COSTING_POLICY_VERSION == "pool-wac-v2"
    identity = CostPool(org_id=1, cost_pool_id=10, product_id=100)
    assert identity == MAHE
    with pytest.raises(TypeError):
        CostPool(org_id=1, branch_id=10, product_id=100)
    with pytest.raises(CostingError, match="Same-pool"):
        dispatch_transfer(CostBalance(identity, D(10), D(100)), identity, D(2))


def test_receipts_recalculate_branch_average():
    original = CostBalance(MAHE, D(100), D(1000))
    result = receive(original, D(100), D(2000), D(200))
    assert result.quantity == 200 and result.value_scr == 3200
    assert result.average_cost_scr == 16
    assert original.quantity == 100 and original.average_cost_scr == 10


def test_issue_uses_unrounded_value_and_clears_final_residue():
    opening = CostBalance(MAHE, D(3), D(10))
    assert opening.average_cost_scr == D("3.333333")
    first = issue(opening, D(2))
    assert first.value_scr == D("6.666667")  # Not 2 * rounded display average.
    last = issue(first.remaining, D(1))
    assert first.value_scr + last.value_scr == 10
    assert last.remaining.quantity == last.remaining.value_scr == last.remaining.average_cost_scr == 0


def test_transfer_adds_freight_at_destination_without_interbranch_profit():
    source = CostBalance(MAHE, D(200), D(2000))
    destination = CostBalance(PRASLIN, D(0), D(0))
    dispatched = dispatch_transfer(source, PRASLIN, D(100))
    assert destination.quantity == 0  # Dispatch does not make destination stock available.
    assert dispatched.source_remaining.value_scr == 1000
    assert dispatched.in_transit.carried_value_scr == 1000
    received = receive_transfer(destination, dispatched.in_transit, D(100), D(200))
    assert received.destination_balance.average_cost_scr == 12
    assert received.destination_balance.value_scr == 1200
    assert received.in_transit_remaining.quantity == received.in_transit_remaining.carried_value_scr == 0
    assert dispatched.source_remaining.value_scr + received.destination_balance.value_scr == source.value_scr + 200


def test_partial_deliveries_leave_unreceived_goods_in_transit():
    dispatched = dispatch_transfer(CostBalance(MAHE, D(200), D(2000)), PRASLIN, D(100))
    freight = allocate_additional_cost(D(200), {"first": D(40), "second": D(60)})
    first = receive_transfer(CostBalance(PRASLIN, D(50), D(550)), dispatched.in_transit, D(40), freight["first"])
    assert first.destination_balance.quantity == 90
    assert first.destination_balance.value_scr == 1030
    assert first.in_transit_remaining.quantity == 60
    assert first.in_transit_remaining.carried_value_scr == 600
    second = receive_transfer(first.destination_balance, first.in_transit_remaining, D(60), freight["second"])
    assert second.destination_balance.quantity == 150
    assert second.destination_balance.value_scr == 1750
    assert second.destination_balance.average_cost_scr == D("11.666667")
    assert second.in_transit_remaining.carried_value_scr == 0


def test_partial_transfer_rounding_conserves_source_value():
    dispatched = dispatch_transfer(CostBalance(MAHE, D(3), D(10)), PRASLIN, D(3))
    destination, transit = CostBalance(PRASLIN, D(0), D(0)), dispatched.in_transit
    portions = []
    for _ in range(3):
        result = receive_transfer(destination, transit, D(1))
        destination, transit = result.destination_balance, result.in_transit_remaining
        portions.append(result.carried_value_received_scr)
    assert sum(portions) == 10 and destination.value_scr == 10
    assert transit.quantity == transit.carried_value_scr == 0


@pytest.mark.parametrize("quantity", [D(0), D(-1), D("NaN"), D("Infinity"), D("0.0000001"), 1.5, "1"])
def test_invalid_issue_quantities_are_rejected(quantity):
    with pytest.raises(CostingError):
        issue(CostBalance(MAHE, D(100), D(1000)), quantity)


@pytest.mark.parametrize("value", [D(-1), D("NaN"), D("Infinity"), D("0.0000001"), 1.5, MAX_VALUE + D(1)])
def test_invalid_receipt_costs_are_rejected(value):
    with pytest.raises(CostingError):
        receive(CostBalance(MAHE, D(0), D(0)), D(1), value)


def test_zero_cost_goods_are_supported_but_zero_quantity_value_is_not():
    free = receive(CostBalance(MAHE, D(0), D(0)), D(5), D(0))
    assert issue(free, D(5)).value_scr == 0
    with pytest.raises(CostingError):
        CostBalance(MAHE, D(0), D(1))


def test_no_negative_stock_or_quantity_overflow():
    with pytest.raises(CostingError, match="Insufficient"):
        issue(CostBalance(MAHE, D(1), D(10)), D(2))
    with pytest.raises(CostingError):
        receive(CostBalance(MAHE, MAX_QUANTITY, D(0)), D(1), D(0))
    with pytest.raises(CostingError):
        receive(CostBalance(MAHE, D(1), MAX_VALUE), D(1), D(1))


@pytest.mark.parametrize("destination", [CostPool(2, 20, 100), CostPool(1, 20, 999), MAHE])
def test_transfer_rejects_wrong_entity_product_or_same_branch(destination):
    with pytest.raises(CostingError):
        dispatch_transfer(CostBalance(MAHE, D(100), D(1000)), destination, D(1))


def test_receipt_rejects_wrong_destination_and_excess_delivery():
    dispatched = dispatch_transfer(CostBalance(MAHE, D(100), D(1000)), PRASLIN, D(1))
    with pytest.raises(CostingError, match="destination"):
        receive_transfer(CostBalance(MAHE, D(0), D(0)), dispatched.in_transit, D(1))
    with pytest.raises(CostingError, match="in-transit"):
        receive_transfer(CostBalance(PRASLIN, D(0), D(0)), dispatched.in_transit, D(2))


def test_allocation_is_exact_and_independent_of_mapping_order():
    first = allocate_additional_cost(D("0.000002"), {"c": D(1), "a": D(1), "b": D(1)})
    second = allocate_additional_cost(D("0.000002"), {"b": D(1), "c": D(1), "a": D(1)})
    assert first == second == {"a": D("0.000001"), "b": D("0.000001"), "c": D(0)}
    assert allocate_additional_cost(D(10), {"a": D(0), "b": D(1)}) == {"a": D(0), "b": D(10)}


@pytest.mark.parametrize("bases", [{}, {"a": D(0)}, {"": D(1)}, {"a": D(-1)}, {"a": 1.1}])
def test_allocation_rejects_invalid_basis(bases):
    with pytest.raises(CostingError):
        allocate_additional_cost(D(1), bases)


def test_amounts_are_independent_of_caller_decimal_precision():
    with localcontext() as context:
        context.prec, context.rounding = 6, ROUND_DOWN
        context.traps[Inexact] = True
        balance = CostBalance(MAHE, D(3), D("1000000000000.000001"))
        outgoing = issue(balance, D(2))
        assert outgoing.value_scr == D("666666666666.666667")
        assert outgoing.remaining.value_scr == D("333333333333.333334")
        assert sum(allocate_additional_cost(D("0.000002"), {"a": D(1), "b": D(2)}).values()) == D("0.000002")


def test_balances_cannot_be_mutated():
    balance = CostBalance(MAHE, D(100), D(1000))
    with pytest.raises(FrozenInstanceError):
        balance.quantity = D(0)


def test_repeated_partial_issues_and_allocations_conserve_value():
    random = Random(20261002)
    for _ in range(200):
        quantity = random.randint(2, 100)
        opening_value = D(random.randint(0, 10**12)) / D(10**6)
        balance = CostBalance(MAHE, D(quantity), opening_value)
        issued = D(0)
        while balance.quantity:
            result = issue(balance, D(random.randint(1, int(balance.quantity))))
            issued += result.value_scr
            balance = result.remaining
        assert issued == opening_value and balance.value_scr == 0
        bases = {str(index): D(random.randint(0, 1000)) for index in range(10)}
        allocation = allocate_additional_cost(opening_value, bases)
        assert sum(allocation.values()) == opening_value
        assert all(value >= 0 for value in allocation.values())

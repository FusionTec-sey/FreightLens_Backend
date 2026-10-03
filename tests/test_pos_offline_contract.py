"""Design-contract experiments only; not production durability/transport tests."""
from dataclasses import replace
from decimal import Decimal as D
from itertools import permutations

import pytest

from prototypes.pos_offline_contract import Cloud, Store, Event, example, finalize, transfer_cost_example


def test_costing_options_have_different_results():
    result = example()
    assert result["global_receipt_first"]["issue_costs"][("praslin", "sale-1")] == D("666.666667")
    assert result["authority_pools"]["issue_costs"][("praslin", "sale-1")] == D(500)
    assert result["global_sale_first"]["issue_costs"][("praslin", "sale-1")] == D(500)
    assert result["linked_cost_adjustment"] == D("166.666667")
    for name in ("global_receipt_first", "authority_pools", "global_sale_first"):
        assert result[name]["closing_quantity"] == 250
        assert result[name]["closing_value"] + sum(result[name]["issue_costs"].values()) == D(4000)


def test_distribution_cost_is_attributed_to_destination_not_profit():
    result = transfer_cost_example()
    assert result["main_warehouse_remaining_value"] == D(1000)
    assert result["praslin_received_value"] == D(1200)
    assert result["praslin_unit_cost"] == D(12)
    assert result["main_warehouse_remaining_value"] + result["praslin_received_value"] == result["consolidated_stock_value"] == D(2200)
    assert result["main_warehouse_remaining_quantity"] + result["praslin_received_quantity"] == 200


@pytest.mark.parametrize("failure,expected", [("before_commit", 100), ("after_commit", 95)])
def test_interrupted_local_transition_can_retry(failure, expected):
    store = Store(1, "mahe", D(100))
    with pytest.raises(RuntimeError):
        store.post("sale", "issue", D(5), fail_at=failure)
    assert store.quantity == expected
    first = store.post("sale", "issue", D(5))
    assert store.post("sale", "issue", D(5)) == first
    assert store.quantity == 95 and len(store.pending) == 1


def test_lost_cloud_ack_resends_without_double_posting():
    store, cloud = Store(1, "mahe", D(100)), Cloud(1, {"mahe": D(100)})
    event = store.post("sale", "issue", D(5))
    cloud.receive(event, "mahe")  # Simulate response lost: do not acknowledge locally.
    assert len(store.pending) == 1
    store.acknowledge(cloud.receive(store.pending[0], "mahe"))
    assert not store.pending
    assert cloud.quantities["mahe"] == store.quantity == 95
    assert len(cloud.inbox) == 1


def test_reversed_delivery_buffers_missing_sequence():
    store, cloud = Store(1, "mahe", D(100)), Cloud(1, {"mahe": D(100)})
    first = store.post("receipt", "receipt", D(10), D(5))
    second = store.post("sale", "issue", D(105))
    cloud.receive(second, "mahe")
    assert cloud.quantities["mahe"] == 100 and cloud.sequences["mahe"] == 0
    cloud.receive(first, "mahe")
    assert cloud.quantities["mahe"] == 5 and cloud.sequences["mahe"] == 2


@pytest.mark.parametrize("change", [{"quantity": D(6)}, {"operation": "different"}])
def test_conflicting_replay_or_sequence_changes_nothing(change):
    cloud = Cloud(1, {"mahe": D(100)})
    event = Store(1, "mahe", D(100)).post("sale", "issue", D(5))
    cloud.receive(event, "mahe")
    with pytest.raises(ValueError):
        cloud.receive(replace(event, **change), "mahe")
    assert cloud.quantities["mahe"] == 95 and len(cloud.inbox) == 1


@pytest.mark.parametrize("org,node,principal", [(2, "mahe", "mahe"), (1, "praslin", "mahe"), (1, "unknown", "unknown")])
def test_cloud_rejects_wrong_tenant_or_authority(org, node, principal):
    cloud = Cloud(1, {"mahe": D(100), "praslin": D(100)})
    with pytest.raises(ValueError):
        cloud.receive(Event(org, node, 1, "sale", "issue", D(5)), principal)
    assert not cloud.inbox and cloud.quantities["mahe"] == 100


def test_store_cannot_spend_remote_stock_or_change_operation():
    store = Store(1, "mahe", D(1))
    with pytest.raises(ValueError):
        store.post("sale", "issue", D(2))
    store.post("sale", "issue", D(1))
    with pytest.raises(ValueError):
        store.post("sale", "issue", D(2))
    assert store.quantity == 0 and len(store.events) == 1


def test_fixed_complete_manifest_is_independent_of_network_delivery():
    a, b = Store(1, "mahe", D(100)), Store(1, "praslin", D(100))
    events = [a.post("receipt", "receipt", D(100), D(20)),
              b.post("sale", "issue", D(50)), b.post("sale2", "issue", D(10))]
    manifest = [event.key for event in events]
    openings = {"mahe": (D(100), D(10)), "praslin": (D(100), D(10))}
    expected = finalize(events, openings, manifest, {"mahe": 1, "praslin": 2}, "organisation")
    for delivery in permutations(events):
        cloud = Cloud(1, {"mahe": D(100), "praslin": D(100)})
        for event in delivery:
            cloud.receive(event, event.node)
            cloud.receive(event, event.node)
        assert finalize(cloud.inbox.values(), openings, manifest,
            {"mahe": 1, "praslin": 2}, "organisation") == expected


def test_cannot_finalize_when_an_offline_node_has_missing_events():
    event = Store(1, "mahe", D(100)).post("receipt", "receipt", D(100), D(20))
    openings = {"mahe": (D(100), D(10)), "praslin": (D(100), D(10))}
    with pytest.raises(ValueError, match="Missing"):
        finalize([event], openings, [event.key], {"mahe": 1, "praslin": 1}, "organisation")


def test_global_cost_pool_does_not_enable_remote_stock_issue():
    event = Event(1, "praslin", 1, "sale", "issue", D(2))
    with pytest.raises(ValueError, match="another store"):
        finalize([event], {"mahe": (D(100), D(10)), "praslin": (D(1), D(10))},
            [event.key], {"mahe": 0, "praslin": 1}, "organisation")


@pytest.mark.parametrize("quantity", [D("NaN"), D("Infinity"), D(-1), D(0), 1.5])
def test_invalid_quantity_never_enters_outbox(quantity):
    store = Store(1, "mahe", D(100))
    with pytest.raises(ValueError):
        store.post("sale", "issue", quantity)
    assert not store.events and store.quantity == 100


def test_final_issue_clears_rounding_residue():
    events = [Event(1, "mahe", 1, "one", "issue", D(1)),
              Event(1, "mahe", 2, "two", "issue", D(2))]
    result = finalize(events, {"mahe": (D(3), D("3.333333"))},
        [event.key for event in events], {"mahe": 2}, "organisation")
    assert result["closing_quantity"] == 0 and result["closing_value"] == 0
    assert sum(result["issue_costs"].values()) == D("9.999999")


def test_cloud_invalid_contiguous_stream_changes_nothing():
    cloud = Cloud(1, {"mahe": D(1)})
    with pytest.raises(ValueError):
        cloud.receive(Event(1, "mahe", 1, "sale", "issue", D(2)), "mahe")
    assert not cloud.inbox and cloud.sequences["mahe"] == 0 and cloud.quantities["mahe"] == 1


def test_manifest_cannot_reorder_one_authority_or_duplicate_events():
    events = [Event(1, "mahe", 1, "one", "issue", D(1)),
              Event(1, "mahe", 2, "two", "issue", D(1))]
    for manifest in ([events[1].key, events[0].key], [events[0].key, events[0].key]):
        with pytest.raises(ValueError):
            finalize(events, {"mahe": (D(10), D(5))}, manifest, {"mahe": 2}, "organisation")


def test_finalization_never_pools_different_tenants():
    events = [Event(1, "mahe", 1, "one", "issue", D(1)),
              Event(2, "praslin", 1, "two", "issue", D(1))]
    with pytest.raises(ValueError, match="organisations"):
        finalize(events, {"mahe": (D(10), D(5)), "praslin": (D(10), D(5))},
            [event.key for event in events], {"mahe": 1, "praslin": 1}, "organisation")

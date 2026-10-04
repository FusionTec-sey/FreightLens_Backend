"""T16 partial collection against exact T13 invoice reservations."""
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from Model.containermgmt.Inventory.CostPool import BranchCostPool, InventoryCostPool
from Model.containermgmt.Inventory.PostingAuthority import (
    BranchAuthorityEpoch, CostPoolAuthorityEpoch, StoreNode,
)
from Model.containermgmt.Inventory.PostingOperation import PostingOperation
from Model.containermgmt.Inventory.StockLedger import StockBalance, StockMovement, StockReservation
from Model.containermgmt.Inventory.Valuation import InventoryValuation
from Model.containermgmt.Orders.SalesCollection import SalesCollection, SalesCollectionAllocation
from Model.containermgmt.Orders.SalesPosting import SalesInvoiceReservation
from Schema.BranchCounterSchema import CounterSave
from Schema.SalesCollectionSchema import SalesCollectionAllocationInput, SalesCollectionCreate
from Services.inventory_costing_service import COSTING_POLICY_VERSION
from Services.inventory_handover_movement_service import handover_reserved_stock
from Services.inventory_posting_service import PostingConflict
from Services.posting_authority_service import AuthorityClaim, CostPoolAuthorityClaim
from Services.sales_collection_service import (
    invoice_fulfilment_status, post_collection, read_collection_options,
)
from Services.sales_posting_service import read_invoice
from Routes.Inventory.BranchCounterRouter import save_counter
from tests.test_sales_posting import NOW, _create, _finalize, posting  # noqa: F401
from tests.test_sales_transaction_pricing import floor_api  # noqa: F401
from tests.test_sales_intent_api import api  # noqa: F401
from tests.test_sales_intent_sources import source  # noqa: F401
from tests.test_policy_activation import activation  # noqa: F401
from tests.test_policy_manager_cases import policy_cases  # noqa: F401
from tests.test_inventory_policy_drafts import draft  # noqa: F401
from tests.test_inventory_locations import locations  # noqa: F401


COLLECTION_TIME = datetime(2026, 10, 5, 11, 0, tzinfo=timezone.utc)


@pytest.fixture
def collectible(posting):
    f = posting
    _create(f); _finalize(f)
    counter_key = uuid4()
    counter = save_counter(f.own, counter_key, CounterSave.model_validate({
        "operation_key": str(uuid4()), "expected_version": 0, "code": "T16",
        "config": {"name": "Synthetic collection", "purpose": "COLLECTION",
                   "is_enabled": True}}), f.db, f.context,
        type("Actor", (), {"id": f.user.id})())

    hold = f.db.query(StockReservation).filter_by(
        org_id=f.org_a, reservation_key=f.posting_reservation_key).one()
    invoice_binding = f.db.query(SalesInvoiceReservation).filter_by(
        org_id=f.org_a, invoice_key=f.posting_invoice_key,
        reservation_key=f.posting_reservation_key).one()
    balance = f.db.get(StockBalance, hold.balance_id)
    node_key = uuid4()
    node = StoreNode(org_id=f.org_a, node_key=node_key, created_by=f.user.id)
    pool = InventoryCostPool(org_id=f.org_a, code="T16", name="T16 synthetic pool",
        created_by=f.user.id)
    f.db.add_all([node, pool]); f.db.flush()
    f.db.add_all([
        BranchAuthorityEpoch(org_id=f.org_a, branch_id=f.own, node_id=node.id,
            epoch=1, state="ACTIVE", reason="Synthetic collection authority",
            created_by=f.user.id),
        BranchCostPool(org_id=f.org_a, branch_id=f.own, cost_pool_id=pool.id,
            created_by=f.user.id),
        CostPoolAuthorityEpoch(org_id=f.org_a, cost_pool_id=pool.id,
            node_id=node.id, epoch=1, state="ACTIVE",
            reason="Synthetic collection cost authority", created_by=f.user.id),
    ])
    opening_key, reserve_key = uuid4(), uuid4()
    f.db.add_all([
        PostingOperation(org_id=f.org_a, operation_key=opening_key,
            kind="test.collection.opening", request_digest="a" * 64,
            result={}, event_payload={}, created_by=f.user.id),
        PostingOperation(org_id=f.org_a, operation_key=reserve_key,
            kind="test.collection.reserve", request_digest="b" * 64,
            result={}, event_payload={}, created_by=f.user.id),
        StockMovement(org_id=f.org_a, balance_id=balance.id,
            operation_key=opening_key, version=1, kind="OPENING",
            reason="Synthetic collection opening", on_hand_delta=balance.on_hand,
            reserved_delta=0, on_hand=balance.on_hand, reserved=0,
            damaged=0, quarantined=0, created_by=f.user.id),
        StockMovement(org_id=f.org_a, balance_id=balance.id,
            reservation_id=hold.id, operation_key=reserve_key, version=2,
            kind="RESERVE", reason="Synthetic collection reservation",
            on_hand_delta=0, reserved_delta=balance.reserved,
            on_hand=balance.on_hand, reserved=balance.reserved,
            damaged=0, quarantined=0, created_by=f.user.id),
    ])
    f.db.flush()
    f.db.add(InventoryValuation(org_id=f.org_a, kind="OPENING",
        source_valuation_id=None, operation_key=opening_key,
        cost_pool_id=pool.id, product_id=balance.product_id,
        balance_id=balance.id, source_version=1, version=1,
        base_unit=balance.base_unit, quantity=balance.on_hand,
        goods_value_scr=Decimal("240"), additional_cost_scr=0,
        pool_quantity=balance.on_hand, pool_value_scr=Decimal("240"),
        calculation_policy=COSTING_POLICY_VERSION, currency="SCR",
        status="UNRECONCILED", reason="Synthetic collection valuation",
        created_by=f.user.id))
    f.db.commit()
    f.collection_counter_key = counter_key
    f.collection_counter_id = counter.id
    f.collection_balance_id = balance.id
    f.collection_line_key = invoice_binding.line_key
    f.stock_claim = AuthorityClaim(f.org_a, f.own, node_key, 1)
    f.cost_claim = CostPoolAuthorityClaim(f.org_a, pool.id, node_key, 1)
    f.collection_key = uuid4()
    f.collection_operation_key = uuid4()

    def payload(quantity="10", stock_version=2, **changes):
        values = dict(collection_key=f.collection_key,
            operation_key=f.collection_operation_key,
            invoice_key=f.posting_invoice_key, branch_id=f.own,
            counter_key=f.collection_counter_key,
            expected_branch_settings_version=1,
            expected_counter_settings_version=1,
            expected_assignment_version=1,
            collector_name="Synthetic collector",
            collector_contact="+248 000 0000",
            allocations=[SalesCollectionAllocationInput(
                line_key=f.collection_line_key,
                reservation_key=f.posting_reservation_key,
                quantity=quantity, expected_stock_version=stock_version)])
        values.update(changes)
        return SalesCollectionCreate(**values)
    f.collection_payload = payload
    def collect(request=None, **changes):
        f.db.connection()
        result = post_collection(
            f.db, f.context, f.user.id, request or payload(**changes),
            stock_authority=f.stock_claim, cost_authority=f.cost_claim,
            authorize=lambda db: None, instant=COLLECTION_TIME)
        f.db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        f.db.execute(text("SET CONSTRAINTS ALL DEFERRED"))
        f.db.commit()
        return result
    f.collect = collect
    return f


def test_partial_then_final_collection_projects_fulfilment_without_money_leak(collectible):
    f = collectible
    options = read_collection_options(f.db, f.context, f.user.id,
        f.posting_invoice_key, authorize=lambda db: None)
    assert options["payment_status"] == "PAID"
    assert options["fulfilment_status"] == "AWAITING_COLLECTION"
    assert options["reservations"][0]["remaining"] == "24.000000"
    assert "valuation" not in str(options).lower() and "account" not in str(options).lower()

    first = f.collect()
    assert not first.replayed
    assert first.result["fulfilment_status"] == "PARTIALLY_COLLECTED"
    assert first.result["allocations"][0]["quantity"] == "10.000000"
    assert invoice_fulfilment_status(
        f.db, f.context, f.posting_invoice_key) == "PARTIALLY_COLLECTED"
    assert read_invoice(f.db, f.context, f.posting_invoice_key,
        authorize=lambda db: None)["fulfilment_status"] == \
        "PARTIALLY_COLLECTED"

    f.collection_key, f.collection_operation_key = uuid4(), uuid4()
    second = f.collect(quantity="14", stock_version=3)
    assert second.result["fulfilment_status"] == "COLLECTED"
    assert f.db.query(SalesCollection).filter_by(org_id=f.org_a).count() == 2
    assert f.db.query(SalesCollectionAllocation).filter_by(org_id=f.org_a).count() == 2
    assert f.db.query(StockMovement).filter_by(
        org_id=f.org_a, kind="HANDOVER").count() == 2


def test_collection_replay_has_one_effect_and_changed_intent_conflicts(collectible):
    f = collectible
    first = f.collect()
    replay = f.collect()
    assert replay.replayed and replay.result == first.result
    assert f.db.query(StockMovement).filter_by(
        org_id=f.org_a, kind="HANDOVER").count() == 1
    with pytest.raises(PostingConflict):
        f.collect(request=f.collection_payload(quantity="9"))


def test_collection_rejects_excess_and_stale_stock(collectible):
    f = collectible
    with pytest.raises(PostingConflict, match="exceeds"):
        f.collect(quantity="25")
    with pytest.raises(PostingConflict, match="Stock version"):
        f.collect(request=f.collection_payload(quantity="1", stock_version=3))


def test_direct_handover_of_posted_hold_requires_collection_history(collectible):
    f = collectible
    f.db.connection()
    with pytest.raises(DBAPIError, match="collection"):
        handover_reserved_stock(f.db, f.context, f.user.id, uuid4(),
            balance_id=f.collection_balance_id,
            reservation_key=f.posting_reservation_key,
            source_line_key=f.db.query(StockReservation).filter_by(
                reservation_key=f.posting_reservation_key).one().source_line_key,
            quantity=Decimal("1"), input_unit="PCS",
            expected_stock_version=2, expected_valuation_version=1,
            reason="Synthetic bypass attempt", stock_authority=f.stock_claim,
            cost_authority=f.cost_claim, authorize_stock=lambda db: None,
            authorize_financial=lambda db: None)
        f.db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    f.db.rollback()


def test_collection_api_enforces_permission_and_returns_redacted_history(
        collectible, monkeypatch):
    import importlib
    router_module = importlib.import_module(
        "Routes.Orders.SalesCollectionRouter")
    from Routes.Orders.SalesCollectionRouter import SalesCollectionRouter
    f = collectible
    if not any(route.path == "/sales/collections/{collection_key}"
            for route in f.app.routes):
        f.app.include_router(SalesCollectionRouter)
    base = f.user.access_policy
    f.user.access_policy = replace(base,
        permission_names=frozenset(set(base.permission_names) | {
            "View_Sale", "View_Product", "View_Customer",
            "View_Personal_Data"}),
        module_names=frozenset(set(base.module_names) | {"SALES"}),
        field_permissions={**base.field_permissions,
            "PERSONAL": "View_Personal_Data"})
    denied = f.client.get(
        f"/sales/invoices/{f.posting_invoice_key}/collection-options")
    assert denied.status_code == 403
    f.user.access_policy = replace(f.user.access_policy,
        permission_names=frozenset(
            set(f.user.access_policy.permission_names) | {"Collect_Sale"}))

    class Runtime:
        def __init__(self, claim): self.claim = claim
        def claim_for(self, db, context, scope_id): return self.claim

    monkeypatch.setattr(router_module, "server_stock_runtime",
        lambda: Runtime(f.stock_claim))
    monkeypatch.setattr(router_module, "server_cost_runtime",
        lambda: Runtime(f.cost_claim))
    options = f.client.get(
        f"/sales/invoices/{f.posting_invoice_key}/collection-options")
    assert options.status_code == 200, options.text
    assert options.json()["payment_status"] == "PAID"
    assert "account" not in options.text.lower()
    assert "valuation" not in options.text.lower()
    payload = f.collection_payload().model_dump(mode="json")
    response = f.client.put(
        f"/sales/collections/{f.collection_key}", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["collection"]["fulfilment_status"] == \
        "PARTIALLY_COLLECTED"
    assert "account" not in response.text.lower()
    assert "issued_value" not in response.text.lower()


def test_sales_collection_migration_replays(test_engine, monkeypatch):
    from Utils import migrate_20261005_sales_collection as migration
    monkeypatch.setattr(migration, "engine", test_engine)
    migration.ensure_sales_collection_schema()
    migration.ensure_sales_collection_schema()

from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from Model.containermgmt.Inventory.StockLedger import StockBalance, StockMovement
from Model.containermgmt.Inventory.Valuation import InventoryValuation
from Model.containermgmt.Orders.SalesReturn import SalesCreditNoteLine
from Schema.StockConditionSchema import StockConditionRequest
from Services.inventory_condition_movement_service import transition_return_condition
from Services.inventory_posting_service import PostingConflict
from Services.manager_case_service import request_case, review_case
from Services.stock_condition_service import (
    list_return_condition_sources,
    load_return_condition_binding,
    reload_return_condition_binding,
)
from Utils.org_filter import OrgContext
from tests.test_sales_returns_integration import (
    _approved_return,
    _run_deferred_guards,
    returnable_sale,  # noqa: F401
    t18_schema,  # noqa: F401
)
from tests.test_sales_collection import collectible  # noqa: F401
from tests.test_sales_posting import NOW, _create, _finalize, posting  # noqa: F401
from tests.test_sales_transaction_pricing import floor_api  # noqa: F401
from tests.test_sales_intent_api import api  # noqa: F401
from tests.test_sales_intent_sources import source  # noqa: F401
from tests.test_policy_activation import activation  # noqa: F401
from tests.test_policy_manager_cases import policy_cases  # noqa: F401
from tests.test_inventory_policy_drafts import draft  # noqa: F401
from tests.test_inventory_locations import locations  # noqa: F401


@pytest.fixture(scope="module")
def condition_schema(t18_schema, test_engine):
    from Utils import migrate_20261005_stock_conditions as migration

    original = migration.engine
    migration.engine = test_engine
    try:
        migration.ensure_stock_condition_schema()
        migration.ensure_stock_condition_schema()
        yield
    finally:
        migration.engine = original


@pytest.fixture
def condition_return(condition_schema, returnable_sale):
    f = returnable_sale
    flow = _approved_return(f)
    result = f.process_return(flow.claim.return_key, flow.process_payload)
    line = f.db.query(SalesCreditNoteLine).filter_by(
        org_id=f.org_a,
        credit_note_key=result["credit_note"]["credit_note_key"],
    ).one()
    f.condition_line = line
    return f


def _request_and_review(f, quantity="1.000000"):
    binding = load_return_condition_binding(
        f.db, f.context, f.condition_line.id, Decimal(quantity), lock=True)
    case_key = uuid4()
    requested = request_case(
        f.db, f.context, f.user.id, case_key,
        binding=binding, reason="Synthetic damaged return disposition",
        load_binding=lambda db: reload_return_condition_binding(db, f.context, binding),
        authorize=lambda db: None,
    )
    _run_deferred_guards(f.db)
    f.db.commit()
    review_key = uuid4()
    f.db.connection()
    reviewed = review_case(
        f.db, f.context, f.return_reviewer_id, review_key,
        case_key=case_key, binding=binding, expected_version=1,
        outcome="APPROVED", reason="Independent condition review",
        load_binding=lambda db: reload_return_condition_binding(
            db, f.context, binding, current_case_key=case_key),
        authorize=lambda db: None,
    )
    _run_deferred_guards(f.db)
    f.db.commit()
    assert requested.replayed is False and reviewed.replayed is False
    return case_key, binding


def test_exact_reviewed_transition_conserves_stock_and_value_with_stable_replay(condition_return):
    f = condition_return
    case_key, binding = _request_and_review(f)
    balance = f.db.get(StockBalance, f.condition_line.balance_id)
    before = tuple(Decimal(value) for value in (
        balance.on_hand, balance.reserved, balance.damaged,
        balance.quarantined,
    )) + (balance.version,)
    valuations = [(
        row.id, row.version, Decimal(row.quantity), Decimal(row.goods_value_scr),
        Decimal(row.pool_quantity), Decimal(row.pool_value_scr),
    ) for row in f.db.query(InventoryValuation).filter_by(
        org_id=f.org_a, balance_id=balance.id).order_by(InventoryValuation.id)]
    operation_key = uuid4()
    outcome = transition_return_condition(
        f.db, f.context, f.user.id, operation_key,
        case_key=case_key, binding=binding,
        reason="Approved returned item is damaged",
        authority=f.stock_claim, authorize=lambda db: None,
    )
    _run_deferred_guards(f.db)
    f.db.commit()
    f.db.connection()
    replay = transition_return_condition(
        f.db, f.context, f.user.id, operation_key,
        case_key=case_key, binding=binding,
        reason="Approved returned item is damaged",
        authority=f.stock_claim, authorize=lambda db: None,
    )
    _run_deferred_guards(f.db)
    f.db.commit()

    after = f.db.get(StockBalance, balance.id)
    assert outcome.replayed is False and replay.replayed is True
    assert Decimal(after.on_hand) == before[0]
    assert Decimal(after.reserved) == before[1]
    assert Decimal(after.damaged) == before[2] + Decimal("1.000000")
    assert Decimal(after.quarantined) == before[3] - Decimal("1.000000")
    assert (Decimal(after.on_hand) - Decimal(after.reserved) - Decimal(after.damaged)
            - Decimal(after.quarantined)) == (
                before[0] - before[1] - before[2] - before[3])
    assert after.version == before[4] + 1
    assert f.db.query(StockMovement).filter_by(
        org_id=f.org_a, operation_key=operation_key, kind="CONDITION").count() == 1
    assert valuations == [(
        row.id, row.version, Decimal(row.quantity), Decimal(row.goods_value_scr),
        Decimal(row.pool_quantity), Decimal(row.pool_value_scr),
    ) for row in f.db.query(InventoryValuation).filter_by(
        org_id=f.org_a, balance_id=balance.id).order_by(InventoryValuation.id)]
    with pytest.raises(PostingConflict):
        load_return_condition_binding(
            f.db, f.context, f.condition_line.id, Decimal("1.000000"), lock=True)
    f.db.rollback()


def test_source_read_is_scoped_exact_paginated_and_reports_pending(condition_return):
    f = condition_return
    total, items = list_return_condition_sources(f.db, f.context, page=1, limit=1)
    assert total >= 1 and len(items) == 1
    row = items[0]
    assert row["credit_note_line_id"] == f.condition_line.id
    assert row["branch_name"] and row["location_name"]
    assert row["product_name"] and row["product_sku"]
    assert row["remaining_eligible"] == "1.000000"
    assert row["pending_review_quantity"] == "0.000000"
    _request_and_review(f, "1.000000")
    _, pending = list_return_condition_sources(f.db, f.context, page=1, limit=100)
    row = next(item for item in pending if item["credit_note_line_id"] == f.condition_line.id)
    assert row["previously_transitioned"] == "0.000000"
    assert row["pending_review_quantity"] == "1.000000"
    assert row["remaining_eligible"] == "0.000000"
    with pytest.raises(PostingConflict):
        load_return_condition_binding(
            f.db, f.context, f.condition_line.id, Decimal("1.000000"), lock=True)
    f.db.rollback()
    foreign = OrgContext(current_org_id=f.org_b, allowed_org_ids=[f.org_a, f.org_b], is_root=True)
    assert list_return_condition_sources(f.db, foreign, page=1, limit=100) == (0, [])


def test_stale_source_tenant_and_branch_authority_fail_closed(condition_return):
    f = condition_return
    case_key, binding = _request_and_review(f, "1.000000")
    second = _approved_return(f, "1.000000")
    f.process_return(second.claim.return_key, second.process_payload)
    with pytest.raises(PostingConflict):
        reload_return_condition_binding(f.db, f.context, binding)
    f.db.rollback()
    foreign = OrgContext(current_org_id=f.org_b, allowed_org_ids=[f.org_a, f.org_b], is_root=True)
    with pytest.raises(LookupError):
        load_return_condition_binding(
            f.db, foreign, f.condition_line.id, Decimal("1.000000"), lock=True)
    f.db.rollback()
    wrong_claim = replace(f.stock_claim, branch_id=f.stock_claim.branch_id + 100000)
    f.db.connection()
    with pytest.raises(PermissionError):
        transition_return_condition(
            f.db, f.context, f.user.id, uuid4(),
            case_key=case_key, binding=binding, reason="Wrong branch authority",
            authority=wrong_claim, authorize=lambda db: None)
    f.db.rollback()


def test_schema_rejects_float_and_database_rejects_unbalanced_condition(condition_return):
    f = condition_return
    with pytest.raises(ValidationError):
        StockConditionRequest(
            operation_key=uuid4(), credit_note_line_id=f.condition_line.id,
            expected_source_version=1, quantity=0.1, reason="No binary floats")
    balance = f.db.get(StockBalance, f.condition_line.balance_id)
    f.db.add(StockMovement(
        org_id=f.org_a, balance_id=balance.id, reservation_id=None,
        operation_key=uuid4(), version=balance.version + 1, kind="CONDITION",
        reason="Invalid direct condition append", created_by=f.user.id,
        on_hand_delta=Decimal("0.000000"), reserved_delta=Decimal("0.000000"),
        on_hand=balance.on_hand, reserved=balance.reserved,
        damaged=Decimal(balance.damaged) + Decimal("0.500000"),
        quarantined=Decimal(balance.quarantined) - Decimal("0.250000"),
    ))
    with pytest.raises(DBAPIError):
        f.db.flush()
        f.db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    f.db.rollback()

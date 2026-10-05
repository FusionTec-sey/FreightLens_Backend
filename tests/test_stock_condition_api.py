from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from Model.db import get_db
from Model.containermgmt.Orders.SalesReturn import SalesCreditNoteLine
from Routes.Inventory.StockConditionRouter import StockConditionRouter
from auth.dependencies import get_current_user, get_org_context
from auth.policy import AccessPolicy, get_request_policy
from tests.test_sales_returns_integration import _approved_return, returnable_sale  # noqa: F401
from tests.test_stock_conditions import (  # noqa: F401
    NOW,
    _create,
    _finalize,
    activation,
    api,
    collectible,
    condition_schema,
    draft,
    floor_api,
    locations,
    policy_cases,
    posting,
    source,
    t18_schema,
)


@pytest.fixture
def condition_api(condition_schema, returnable_sale):
    f = returnable_sale
    flow = _approved_return(f)
    result = f.process_return(flow.claim.return_key, flow.process_payload)
    line = f.db.query(SalesCreditNoteLine).filter_by(
        org_id=f.org_a,
        credit_note_key=result["credit_note"]["credit_note_key"],
    ).one()
    f.api_line = line
    f.api_user = SimpleNamespace(id=f.user.id, roles=[])
    f.permissions = frozenset({
        "View_Product", "Request_StockCondition",
        "Review_StockCondition", "Execute_StockCondition",
    })
    f.api_user.access_policy = AccessPolicy(
        user=f.api_user, org_ids=(f.org_a,), permission_names=f.permissions,
        module_names=frozenset({"INVENTORY"}), field_permissions={},
    )
    app = FastAPI()
    app.include_router(StockConditionRouter)

    def db_dependency():
        yield f.db

    app.dependency_overrides.update({
        get_db: db_dependency,
        get_current_user: lambda: f.api_user,
        get_org_context: lambda: f.context,
        get_request_policy: lambda: f.api_user.access_policy,
    })
    f.condition_url = "/inventory/stock-condition-cases"
    with TestClient(app) as client:
        f.condition_client = client
        yield f


def _request_review_api(f):
    source = f.condition_client.get(f.condition_url + "/sources?limit=1")
    assert source.status_code == 200, source.text
    row = source.json()["items"][0]
    requested = f.condition_client.post(f.condition_url, json={
        "operation_key": str(uuid4()),
        "credit_note_line_id": row["credit_note_line_id"],
        "expected_source_version": row["stock_version"],
        "quantity": "1.000000",
        "reason": "Synthetic API condition review",
    })
    assert requested.status_code == 200, requested.text
    case_key = requested.json()["case_key"]
    f.api_user.id = f.return_reviewer_id
    reviewed = f.condition_client.post(f"{f.condition_url}/{case_key}/review", json={
        "operation_key": str(uuid4()), "expected_version": 1,
        "outcome": "APPROVED", "reason": "Independent API condition review",
    })
    assert reviewed.status_code == 200, reviewed.text
    return case_key


def test_source_options_are_private_named_paginated_and_permission_scoped(condition_api):
    f = condition_api
    response = f.condition_client.get(f.condition_url + "/sources?page=1&limit=1")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert payload["page"] == 1 and payload["limit"] == 1 and payload["total"] >= 1
    row = payload["items"][0]
    assert row["credit_note_line_id"] == f.api_line.id
    assert row["branch_name"] and row["location_name"]
    assert row["product_name"] and row["product_sku"]
    assert row["credit_note_key"] and row["return_key"] and row["invoice_key"]
    filtered = f.condition_client.get(
        f.condition_url + f"/sources?invoice_key={row['invoice_key']}&credit_note_key={row['credit_note_key']}")
    assert filtered.status_code == 200 and filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["credit_note_line_id"] == f.api_line.id
    missing = f.condition_client.get(
        f.condition_url + f"/sources?invoice_key={uuid4()}")
    assert missing.status_code == 200 and missing.json()["items"] == []
    policy = f.api_user.access_policy
    f.api_user.access_policy = replace(
        policy, permission_names=policy.permission_names - {"View_Product"})
    assert f.condition_client.get(f.condition_url + "/sources").status_code == 403
    f.api_user.access_policy = replace(
        policy, permission_names=frozenset({"View_Product"}))
    assert f.condition_client.get(f.condition_url + "/sources").status_code == 403


def test_request_review_execute_and_replay_expose_bounded_effects(condition_api, monkeypatch):
    f = condition_api
    case_key = _request_review_api(f)
    cases = f.condition_client.get(f.condition_url + "?limit=1")
    assert cases.status_code == 200, cases.text
    row = cases.json()["items"][0]
    assert row["case_key"] == case_key and row["product_name"] and row["branch_name"]
    operation_key = str(uuid4())
    monkeypatch.delenv("FREIGHTLENS_LOCAL_STOCK_RUNTIME_JSON", raising=False)
    monkeypatch.setenv("FREIGHTLENS_CLOUD_STOCK_RUNTIME_NODE_KEY", str(f.stock_claim.node_key))
    executed = f.condition_client.post(
        f"{f.condition_url}/{case_key}/execute", json={"operation_key": operation_key})
    assert executed.status_code == 200, executed.text
    body = executed.json()
    assert body["condition_effect"] == "QUARANTINED_TO_DAMAGED"
    assert body["valuation_effect"] == body["accounting_effect"] == body["pricing_effect"] == "NONE"
    replay = f.condition_client.post(
        f"{f.condition_url}/{case_key}/execute", json={"operation_key": operation_key})
    assert replay.status_code == 200 and replay.json()["replayed"] is True


def test_stale_version_tenant_module_and_write_permissions_fail_closed(condition_api):
    f = condition_api
    policy = f.api_user.access_policy
    denied = replace(policy, permission_names=policy.permission_names - {"Request_StockCondition"})
    f.api_user.access_policy = denied
    assert f.condition_client.post(f.condition_url, json={
        "operation_key": str(uuid4()), "credit_note_line_id": f.api_line.id,
        "expected_source_version": 1, "quantity": "0.500000", "reason": "Denied",
    }).status_code == 403
    f.api_user.access_policy = policy
    current = f.condition_client.get(f.condition_url + "/sources").json()["items"][0]
    stale = f.condition_client.post(f.condition_url, json={
        "operation_key": str(uuid4()), "credit_note_line_id": current["credit_note_line_id"],
        "expected_source_version": current["stock_version"] - 1,
        "quantity": "1.000000", "reason": "Stale version",
    })
    assert stale.status_code == 409
    f.context.current_org_id = f.org_b
    assert f.condition_client.get(f.condition_url + "/sources").status_code == 403
    assert f.condition_client.post(f.condition_url, json={
        "operation_key": str(uuid4()), "credit_note_line_id": f.api_line.id,
        "expected_source_version": current["stock_version"],
        "quantity": "1.000000", "reason": "Foreign tenant",
    }).status_code == 403
    f.api_user.access_policy = replace(policy, org_ids=(f.org_a, f.org_b))
    f.context.allowed_org_ids = [f.org_a, f.org_b]
    scoped = f.condition_client.get(f.condition_url + "/sources")
    assert scoped.status_code == 200 and scoped.json()["items"] == []
    f.context.current_org_id = f.org_a
    f.api_user.access_policy = replace(policy, module_names=frozenset())
    assert f.condition_client.get(f.condition_url + "/sources").status_code == 403

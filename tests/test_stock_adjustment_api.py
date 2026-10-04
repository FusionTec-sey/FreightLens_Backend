from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from Model.db import get_db
from Model.containermgmt.Inventory.StockLedger import StockBalance, StockMovement
from Routes.Inventory.StockAdjustmentRouter import StockAdjustmentRouter
from auth.dependencies import get_current_user, get_org_context
from auth.policy import AccessPolicy, get_request_policy
from tests.test_stock_adjustments import adjustments  # noqa: F401
from tests.test_stock_ledger import stock  # noqa: F401


@pytest.fixture
def adjustment_api(adjustments):
    f = adjustments
    f.user = SimpleNamespace(id=f.actor, roles=[])
    f.permissions = {"Request_StockAdjustment", "Review_StockAdjustment", "Execute_StockAdjustment"}
    f.user.access_policy = AccessPolicy(
        user=f.user, org_ids=(f.orgs[0],),
        permission_names=frozenset(f.permissions),
        module_names=frozenset({"INVENTORY"}), field_permissions={},
    )
    f.app = FastAPI()
    f.app.include_router(StockAdjustmentRouter)

    def db_dependency():
        with f.factory() as session:
            yield session

    f.app.dependency_overrides.update({
        get_db: db_dependency,
        get_current_user: lambda: f.user,
        get_org_context: lambda: f.context,
        get_request_policy: lambda: f.user.access_policy,
    })
    f.url = "/inventory/stock-adjustment-cases"
    f.body = {
        "operation_key": str(uuid4()), "balance_id": f.balance,
        "expected_source_version": 1, "target_on_hand": "9.000000",
        "target_damaged": "1.000000", "target_quarantined": "1.000000",
        "reason": "Synthetic count correction",
    }
    with TestClient(f.app) as client:
        f.client = client
        yield f


def request_and_review(f):
    requested = f.client.post(f.url, json=f.body)
    assert requested.status_code == 200, requested.text
    case_key = requested.json()["case_key"]
    assert f.client.post(f.url, json=f.body).json()["replayed"] is True
    review = {"operation_key": str(uuid4()), "expected_version": 1,
              "outcome": "APPROVED", "reason": "Independent review"}
    assert f.client.post(f"{f.url}/{case_key}/review", json=review).status_code == 403
    f.user.id = f.reviewer
    reviewed = f.client.post(f"{f.url}/{case_key}/review", json=review)
    assert reviewed.status_code == 200, reviewed.text
    return case_key


def test_request_review_list_and_execute_exact_adjustment(adjustment_api, monkeypatch):
    f = adjustment_api
    case_key = request_and_review(f)
    page = f.client.get(f.url + f"?view=ALL&limit=1&balance_id={f.balance}").json()
    assert page["total"] == 1
    row = page["items"][0]
    assert row["case_key"] == case_key and row["status"] == "APPROVED"
    assert row["before_on_hand"] == "10.000000" and row["target_on_hand"] == "9.000000"
    operation_key = str(uuid4())
    monkeypatch.delenv("FREIGHTLENS_LOCAL_STOCK_RUNTIME_JSON", raising=False)
    monkeypatch.setenv("FREIGHTLENS_CLOUD_STOCK_RUNTIME_NODE_KEY", str(f.node_key))
    executed = f.client.post(f"{f.url}/{case_key}/execute", json={"operation_key": operation_key})
    assert executed.status_code == 200, executed.text
    assert executed.json()["status"] == "CONSUMED" and executed.json()["on_hand"] == "9.000000"
    assert f.client.post(f"{f.url}/{case_key}/execute",
        json={"operation_key": operation_key}).json()["replayed"] is True
    with f.factory() as db:
        assert db.get(StockBalance, f.balance).on_hand == 9
        assert db.query(StockMovement).filter_by(balance_id=f.balance, kind="ADJUSTMENT").count() == 1


@pytest.mark.parametrize("permission", [
    "Request_StockAdjustment", "Review_StockAdjustment", "Execute_StockAdjustment",
])
def test_each_write_permission_is_independent(adjustment_api, monkeypatch, permission):
    f = adjustment_api
    policy = f.user.access_policy
    if permission == "Request_StockAdjustment":
        f.user.access_policy = replace(policy,
            permission_names=policy.permission_names - {permission})
        assert f.client.post(f.url, json=f.body).status_code == 403
        return
    case_key = request_and_review(f) if permission == "Execute_StockAdjustment" else None
    f.user.access_policy = replace(policy,
        permission_names=policy.permission_names - {permission})
    if permission == "Review_StockAdjustment":
        requested = f.client.post(f.url, json={**f.body, "operation_key": str(uuid4())})
        f.user.id = f.reviewer
        assert f.client.post(f"{f.url}/{requested.json()['case_key']}/review", json={
            "operation_key": str(uuid4()), "expected_version": 1,
            "outcome": "APPROVED", "reason": "Denied"}).status_code == 403
    else:
        monkeypatch.setenv("FREIGHTLENS_CLOUD_STOCK_RUNTIME_NODE_KEY", str(f.node_key))
        assert f.client.post(f"{f.url}/{case_key}/execute",
            json={"operation_key": str(uuid4())}).status_code == 403


def test_runtime_and_tenant_fail_closed(adjustment_api, monkeypatch):
    f = adjustment_api
    case_key = request_and_review(f)
    monkeypatch.delenv("FREIGHTLENS_LOCAL_STOCK_RUNTIME_JSON", raising=False)
    monkeypatch.delenv("FREIGHTLENS_CLOUD_STOCK_RUNTIME_NODE_KEY", raising=False)
    assert f.client.post(f"{f.url}/{case_key}/execute",
        json={"operation_key": str(uuid4())}).status_code == 503
    assert f.client.post(f"{f.url}/{case_key}/execute", json={
        "operation_key": str(uuid4()), "authority": {}}).status_code == 422
    f.context.current_org_id = f.orgs[1]
    assert f.client.get(f.url).json()["items"] == []
    assert f.client.post(f"{f.url}/{case_key}/execute",
        json={"operation_key": str(uuid4())}).status_code == 404


def test_module_and_anonymous_requests_are_denied(adjustment_api):
    f = adjustment_api
    policy = f.user.access_policy
    f.user.access_policy = replace(policy, module_names=frozenset())
    assert f.client.get(f.url).status_code == 403
    f.user.access_policy = policy
    f.app.dependency_overrides.pop(get_current_user)
    f.app.dependency_overrides.pop(get_request_policy)
    assert f.client.get(f.url).status_code == 401
    assert f.client.post(f.url, json=f.body).status_code == 401


from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from Model.db import get_db
from Routes.Inventory.CostReconciliationRouter import CostReconciliationRouter
from auth.dependencies import get_current_user, get_org_context
from auth.policy import AccessPolicy, get_request_policy
from tests.test_cost_reconciliation_checkpoints import closable  # noqa: F401
from tests.test_inventory_valuation import valued  # noqa: F401
from tests.test_stock_ledger import stock  # noqa: F401


@pytest.fixture
def reconciliation_api(closable, monkeypatch):
    f = closable
    permissions = {"View_Product", "View_Financials", "Request_CostReconciliation",
        "Review_CostReconciliation", "Execute_CostReconciliation"}
    f.user = SimpleNamespace(id=f.actor, roles=[])
    f.user.access_policy = AccessPolicy(user=f.user, org_ids=(f.orgs[0],),
        permission_names=frozenset(permissions), module_names=frozenset({"INVENTORY"}),
        field_permissions={"FINANCIAL": "View_Financials"})
    app = FastAPI(); app.include_router(CostReconciliationRouter)
    def db_dependency():
        with f.factory() as db: yield db
    app.dependency_overrides.update({get_db: db_dependency,
        get_current_user: lambda: f.user, get_org_context: lambda: f.context,
        get_request_policy: lambda: f.user.access_policy})
    monkeypatch.setenv("FREIGHTLENS_CLOUD_COST_RUNTIME_NODE_KEY", str(f.node_key))
    with TestClient(app) as client:
        f.client = client
        yield f


def test_request_review_close_and_checkpoint_register(reconciliation_api):
    f = reconciliation_api
    body = {"operation_key": str(uuid4()), "cost_pool_id": f.pool,
        "product_id": f.products[0], "reason": "Confirm exact state"}
    requested = f.client.post("/inventory/cost-reconciliation/cases", json=body)
    assert requested.status_code == 200, requested.text
    case_key = requested.json()["case_key"]
    assert f.client.post("/inventory/cost-reconciliation/cases", json=body).json()["replayed"] is True
    mine = f.client.get(f"/inventory/cost-reconciliation/cases?cost_pool_id={f.pool}&view=MY_REQUESTS").json()
    assert any(row["case_key"] == case_key for row in mine["items"])
    review = {"operation_key": str(uuid4()), "expected_version": 1,
        "outcome": "APPROVED", "reason": "Independent check"}
    assert f.client.post(f"/inventory/cost-reconciliation/cases/{case_key}/review", json=review).status_code == 403
    f.user.id = f.reviewer
    assert f.client.post(f"/inventory/cost-reconciliation/cases/{case_key}/review", json=review).status_code == 200
    close_key = str(uuid4())
    closed = f.client.post(f"/inventory/cost-reconciliation/cases/{case_key}/close",
        json={"operation_key": close_key})
    assert closed.status_code == 200, closed.text
    assert closed.json()["checkpoint_key"] == close_key and closed.json()["status"] == "CLOSED"
    page = f.client.get(f"/inventory/cost-reconciliation/checkpoints?cost_pool_id={f.pool}").json()
    assert any(row["checkpoint_key"] == close_key for row in page["items"])


def test_foreign_and_missing_runtime_paths_fail_closed(reconciliation_api, monkeypatch):
    f = reconciliation_api
    f.context.current_org_id = f.orgs[1]
    assert f.client.get(f"/inventory/cost-reconciliation/cases?cost_pool_id={f.pool}").json()["items"] == []
    f.context.current_org_id = f.orgs[0]
    monkeypatch.delenv("FREIGHTLENS_CLOUD_COST_RUNTIME_NODE_KEY", raising=False)
    response = f.client.post(f"/inventory/cost-reconciliation/cases/{f.case_key}/close",
        json={"operation_key": str(uuid4())})
    assert response.status_code == 503

from types import SimpleNamespace
from uuid import uuid4
import pytest
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient
from auth.module_guard import require_module
from auth.policy import AccessPolicy
from Utils.org_filter import OrgContext
from tests.test_reclassification_proposals import proposal  # noqa: F401
from tests.test_policy_activation_concurrency import reviewed  # noqa: F401
from tests.test_stock_ledger import stock  # noqa: F401

BASE = "/inventory/reclassification-proposals"


@pytest.fixture
def api(proposal):
    from Routes.Inventory.ReclassificationProposalRouter import ReclassificationProposalRouter
    f = proposal
    f.user = SimpleNamespace(id=f.actor, roles=[])
    f.user.access_policy = AccessPolicy(user=f.user, org_ids=tuple(f.orgs), field_permissions={},
        permission_names=frozenset({"View_Product", "Request_InventoryReview", "Review_InventoryPolicy"}),
        module_names=frozenset({"INVENTORY"}))
    f.app = FastAPI()
    f.app.include_router(ReclassificationProposalRouter, dependencies=[Depends(require_module("INVENTORY"))])
    def database():
        with f.factory() as db:
            yield db
    replacements = {"get_db": database, "get_current_user": lambda: f.user,
        "get_org_context": lambda: f.context, "get_request_policy": lambda: f.user.access_policy}
    f.user_dependencies = set()
    def override(dependant):
        for dependency in dependant.dependencies:
            name = getattr(dependency.call, "__name__", "")
            if name in replacements and getattr(dependency.call, "__module__", "").startswith(("auth.", "Model.db")):
                f.app.dependency_overrides[dependency.call] = replacements[name]
                if name == "get_current_user": f.user_dependencies.add(dependency.call)
            override(dependency)
    for route in f.app.routes:
        if hasattr(route, "dependant"): override(route.dependant)
    with TestClient(f.app) as client:
        f.client = client
        yield f


def test_save_list_detail_replay_and_historical_read(api):
    f = api; payload = f.payload.model_dump(mode="json")
    response = f.client.post(BASE, json=payload)
    assert response.status_code == 200, response.text
    assert not response.json()["conversion_enabled"]
    assert f.client.post(BASE, json=payload).json()["replayed"]
    rows = f.client.get(BASE + "?limit=1").json()
    assert rows["total"] == 1 and len(rows["items"]) == 1
    assert "manifest" not in rows["items"][0]
    assert f.client.get(BASE + "?page=2&limit=1").json()["items"] == []
    detail = f.client.get(f"{BASE}/{f.payload.operation_key}").json()
    assert detail["snapshot"]["quantities"]["on_hand"] == "10.000000"
    assert detail["manifest"]["batches"][0]["identity"]["shade"] == "A"
    f.reserve(f.balance)
    assert f.client.post(BASE, json=payload).status_code == 409
    assert f.client.get(f"{BASE}/{f.payload.operation_key}").json()["historical_snapshot"]


@pytest.mark.parametrize("method", ["post", "list", "detail"])
@pytest.mark.parametrize("denial", ["anonymous", "permission", "module"])
def test_all_endpoint_guards(api, method, denial):
    f = api
    if denial == "anonymous":
        for dependency in f.user_dependencies: f.app.dependency_overrides.pop(dependency)
    else:
        f.user.access_policy = AccessPolicy(user=f.user, org_ids=tuple(f.orgs), field_permissions={},
            permission_names=frozenset() if denial == "permission" else frozenset({"View_Product", "Request_InventoryReview"}),
            module_names=frozenset({"INVENTORY"}) if denial == "permission" else frozenset())
    response = f.client.post(BASE, json=f.payload.model_dump(mode="json")) if method == "post" else (
        f.client.get(BASE if method == "list" else f"{BASE}/{f.payload.operation_key}"))
    assert response.status_code == (401 if denial == "anonymous" else 403)


def test_foreign_active_scope_and_unknown_identity_not_exposed(api):
    f = api; f.save()
    f.context = OrgContext(current_org_id=f.orgs[1], allowed_org_ids=f.orgs, is_root=True)
    assert f.client.get(BASE).json()["total"] == 0
    assert f.client.get(f"{BASE}/{f.payload.operation_key}").status_code == 404
    assert f.client.get(f"{BASE}/{uuid4()}").status_code == 404
    assert f.client.post(BASE, json=f.payload.model_dump(mode="json")).status_code == 404


def test_pagination_and_quantity_validation(api):
    f = api
    for query in ("?page=0", "?limit=101", "?balance_id=0"):
        assert f.client.get(BASE + query).status_code == 422
    payload = f.payload.model_dump(mode="json")
    payload["batches"][0]["on_hand"] = 10.0
    assert f.client.post(BASE, json=payload).status_code == 422
    assert f.client.get(BASE).json()["total"] == 0


@pytest.mark.parametrize("parent", ["product", "location", "branch"])
def test_deleted_parent_hides_proposals(api, parent):
    from Model.containermgmt.Orders.Product import Product
    from Model.containermgmt.Inventory.Location import InventoryBranch, StockLocation
    f = api; f.save()
    model, key = {"product": (Product, f.products[0]), "location": (StockLocation, f.locations[0]),
                  "branch": (InventoryBranch, f.branches[0])}[parent]
    with f.factory.begin() as db:
        db.get(model, key).is_deleted = True
    assert f.client.get(BASE).json()["items"] == []
    assert f.client.get(f"{BASE}/{f.payload.operation_key}").status_code == 404


def test_request_and_independent_review_are_replay_safe(api):
    f = api; f.save()
    path = f"{BASE}/{f.payload.operation_key}"
    body = {"operation_key": str(uuid4()), "reason": "Audit checked"}
    response = f.client.post(path + "/request-review", json=body)
    assert response.status_code == 200, response.text
    key = response.json()["case_key"]
    assert f.client.post(path + "/request-review", json=body).json()["replayed"]
    assert f.client.get(path + "/cases?view=MY_REQUESTS").json()["total"] == 1
    review = {"operation_key": str(uuid4()), "expected_version": 1, "outcome": "APPROVED", "reason": "Manifest verified"}
    url = path + f"/cases/{key}/review"
    assert f.client.post(url, json=review).status_code == 403
    f.user.id = f.reviewer
    assert f.client.get(path + "/cases?view=NEEDS_MY_REVIEW").json()["total"] == 1
    assert f.client.post(url, json=review).json()["status"] == "APPROVED"
    assert f.client.post(url, json=review).json()["replayed"]
    assert f.client.get(path + "/cases").json()["items"][0]["status"] == "APPROVED"
    assert f.client.get(path).json()["conversion_enabled"] is False
    f.reserve(f.balance)
    assert f.client.post(url, json=review).status_code == 409


@pytest.mark.parametrize("action", ["request-review", "cases", "review"])
@pytest.mark.parametrize("denial", ["anonymous", "permission", "module", "foreign"])
def test_review_endpoint_boundaries(api, action, denial):
    f = api; f.save()
    path = f"{BASE}/{f.payload.operation_key}"
    body = {"operation_key": str(uuid4()), "reason": "Check"}
    case = f.client.post(path + "/request-review", json=body).json()["case_key"]
    if denial == "anonymous":
        for dependency in f.user_dependencies: f.app.dependency_overrides.pop(dependency)
    elif denial == "foreign":
        f.context = OrgContext(current_org_id=f.orgs[1], allowed_org_ids=f.orgs, is_root=True)
    else:
        f.user.access_policy = AccessPolicy(user=f.user, org_ids=tuple(f.orgs), field_permissions={},
            permission_names=frozenset() if denial == "permission" else frozenset({"Request_InventoryReview", "Review_InventoryPolicy"}),
            module_names=frozenset({"INVENTORY"}) if denial == "permission" else frozenset())
    response = f.client.get(path + "/cases") if action == "cases" else f.client.post(
        path + ("/request-review" if action == "request-review" else f"/cases/{case}/review"),
        json=body if action == "request-review" else {**body, "expected_version": 1, "outcome": "REJECTED"})
    assert response.status_code == (401 if denial == "anonymous" else 404 if denial == "foreign" else 403)

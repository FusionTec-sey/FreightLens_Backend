from uuid import uuid4
import pytest
from Model.Credentials.users import User
from auth.policy import AccessPolicy
from tests.test_inventory_policy_drafts import draft, config  # noqa: F401
from tests.test_inventory_locations import locations  # noqa: F401


@pytest.fixture
def policy_cases(draft):
    f = draft
    assert f.client.put(f.url, json={"expected_version": 0, "config": config()}).status_code == 200
    f.request_payload = {"operation_key": str(uuid4()), "product_id": f.product.id,
                         "expected_source_version": 1, "reason": "Synthetic policy review"}
    f.request_url = "/inventory/manager-cases/policy-activation"
    reviewer = User(username="policy-manager-" + uuid4().hex[:24], password_hash="test-only", org_id=f.org_a)
    f.db.add(reviewer); f.db.commit()
    f.reviewer = reviewer.id
    return f


def review_payload(**changes):
    return {"operation_key": str(uuid4()), "expected_version": 1, "outcome": "APPROVED",
            "reason": "Synthetic reviewed exact policy", **changes}


def test_request_inbox_review_and_no_activation(policy_cases):
    f = policy_cases
    first = f.client.post(f.request_url, json=f.request_payload)
    assert first.status_code == 200 and first.json()["status"] == "REQUESTED"
    assert f.client.post(f.request_url, json=f.request_payload).json()["replayed"]
    page = f.client.get("/inventory/manager-cases?limit=1").json()
    assert page["total"] == 1 and page["items"][0]["config"]["tracking"] == "BATCH"
    review_url = f"/inventory/manager-cases/{first.json()['case_key']}/review"
    data = review_payload()
    assert f.client.post(review_url, json=data).status_code == 403
    f.user.id = f.reviewer
    approved = f.client.post(review_url, json=data)
    assert approved.status_code == 200 and approved.json()["status"] == "APPROVED"
    assert f.client.post(review_url, json=data).json()["replayed"]
    assert f.client.get(f.url).json()["status"] == "DRAFT"
    assert f.client.get("/inventory/manager-cases").json()["items"][0]["reviewer_id"] == f.reviewer


@pytest.mark.parametrize("route", ["request", "list", "review", "personal"])
@pytest.mark.parametrize("denial", ["anonymous", "permission", "module"])
def test_manager_case_route_guards(policy_cases, route, denial):
    f = policy_cases
    if denial == "anonymous":
        for dependency in f.user_dependencies: f.app.dependency_overrides.pop(dependency)
    else:
        f.user.access_policy = AccessPolicy(user=f.user, org_ids=(f.org_a,), field_permissions={},
            permission_names=frozenset() if denial == "permission" else frozenset({"Request_InventoryReview", "Review_InventoryPolicy"}),
            module_names=frozenset({"INVENTORY"}) if denial == "permission" else frozenset())
    if route == "list": response = f.client.get("/inventory/manager-cases")
    elif route == "personal": response = f.client.get("/inventory/manager-cases?view=NEEDS_MY_REVIEW")
    elif route == "request": response = f.client.post(f.request_url, json=f.request_payload)
    else: response = f.client.post(f"/inventory/manager-cases/{uuid4()}/review", json=review_payload())
    assert response.status_code == (401 if denial == "anonymous" else 403)


def test_modified_source_requires_new_review_and_stable_request_id_conflicts(policy_cases):
    f = policy_cases
    case = f.client.post(f.request_url, json=f.request_payload).json()["case_key"]
    assert f.client.put(f.url, json={"expected_version": 1, "config": config(quantity_step="0.1")}).status_code == 200
    f.user.id = f.reviewer
    assert f.client.post(f"/inventory/manager-cases/{case}/review", json=review_payload()).status_code == 409
    assert f.client.post(f.request_url, json=f.request_payload).status_code == 409


def test_foreign_source_and_case_are_not_exposed(policy_cases):
    f = policy_cases
    assert f.client.post(f.request_url, json={**f.request_payload, "product_id": f.foreign_product.id}).status_code == 404
    assert f.client.post(f"/inventory/manager-cases/{uuid4()}/review", json=review_payload()).status_code == 404
    assert f.client.get("/inventory/manager-cases").json()["total"] == 0


def test_list_paginates_and_rejection_is_final(policy_cases):
    f = policy_cases
    keys = []
    for _ in range(2):
        data = {**f.request_payload, "operation_key": str(uuid4())}
        keys.append(f.client.post(f.request_url, json=data).json()["case_key"])
    page = f.client.get("/inventory/manager-cases?limit=1&page=2").json()
    assert len(page["items"]) == 1 and page["total"] == 2 and page["pages"] == 2
    f.user.id = f.reviewer
    url = f"/inventory/manager-cases/{keys[0]}/review"
    assert f.client.post(url, json=review_payload(outcome="REJECTED")).status_code == 200
    assert f.client.post(url, json=review_payload()).status_code == 409


def test_personal_queue_excludes_self_and_decisions_before_pagination(policy_cases):
    f = policy_cases
    keys = [f.client.post(f.request_url, json={**f.request_payload, "operation_key": str(uuid4())}).json()["case_key"] for _ in range(3)]
    base = "/inventory/manager-cases"
    assert f.client.get(base + "?view=NEEDS_MY_REVIEW").json()["total"] == 0
    assert f.client.get(base + "?view=MY_REQUESTS").json()["total"] == 3
    f.user.id = f.reviewer
    assert f.client.get(base + "?view=MY_REQUESTS").json()["total"] == 0
    for key, outcome in zip(keys[:2], ["APPROVED", "REJECTED"]):
        assert f.client.post(f"{base}/{key}/review", json=review_payload(outcome=outcome)).status_code == 200
    result = f.client.get(base + "?view=NEEDS_MY_REVIEW&limit=1").json()
    assert result["total"] == 1 and result["pages"] == 1
    assert result["items"][0]["case_key"] == keys[2]
    assert f.client.get(base + "?view=NEEDS_MY_REVIEW&limit=1&page=2").json()["items"] == []
    assert f.client.get(base).json()["total"] == 3


@pytest.mark.parametrize("view", ["ALL", "NEEDS_MY_REVIEW", "MY_REQUESTS"])
def test_personal_case_views_remain_exact_company_scoped(policy_cases, view):
    f = policy_cases
    assert f.client.post(f.request_url, json=f.request_payload).status_code == 200
    f.context.is_root = True
    f.context.allowed_org_ids = [f.org_a, f.org_b]
    f.context.selected_org_id = f.org_b
    result = f.client.get(f"/inventory/manager-cases?view={view}")
    assert result.status_code == 200 and result.json()["total"] == 0


def test_unknown_case_view_rejected(policy_cases):
    assert policy_cases.client.get("/inventory/manager-cases?view=OTHER_USER").status_code == 422

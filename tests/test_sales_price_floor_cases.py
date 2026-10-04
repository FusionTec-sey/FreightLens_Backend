"""Below-floor review binds exact draft/pricing inputs and has no sale effect."""
from dataclasses import replace
from uuid import uuid4

import pytest

from Model.Credentials.users import User
from auth.policy import AccessPolicy
from tests.test_sales_intent_api import api  # noqa: F401
from tests.test_sales_intent_sources import source  # noqa: F401
from tests.test_policy_activation import activation  # noqa: F401
from tests.test_policy_manager_cases import policy_cases  # noqa: F401
from tests.test_inventory_policy_drafts import draft  # noqa: F401
from tests.test_inventory_locations import locations  # noqa: F401
from tests.test_sales_pricing_preview_api import configured_preview


@pytest.fixture
def floor_api(api):
    from Routes.Orders.SalesPricingRouter import SalesPricingRouter
    f = api
    f.app.include_router(SalesPricingRouter)
    f.permissions |= {"View_Financials", "Request_PriceFloorException",
                      "Review_PriceFloorException"}
    f.user.access_policy = AccessPolicy(user=f.user, org_ids=(f.org_a,),
        permission_names=frozenset(f.permissions), module_names=frozenset({"SALES"}),
        field_permissions={"PERSONAL": "View_Personal_Data"})
    assert f.client.put(f.url, json=f.payload).status_code == 200
    configured_preview(f)
    f.document_key = f.url.rsplit("/", 1)[-1]
    f.case_key = uuid4()
    f.case_body = {"operation_key": str(f.case_key),
        "document_key": f.document_key, "expected_draft_version": 1,
        "reason": "Synthetic customer agreement is below reviewed floor"}
    return f


def _reviewer(f):
    reviewer = User(org_id=f.org_a,
        username="floor-review-" + uuid4().hex[:20],
        password_hash="unusable-test-only")
    f.db.add(reviewer); f.db.commit()
    return reviewer


def test_request_list_and_independent_review_are_exact_and_effect_free(floor_api):
    from Model.containermgmt.Inventory.ManagerCase import ManagerCase, ManagerCaseUse
    f = floor_api
    response = f.client.post("/sales/pricing/floor-cases", json=f.case_body)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "REQUESTED"
    replay = f.client.post("/sales/pricing/floor-cases", json=f.case_body)
    assert replay.status_code == 200 and replay.json()["replayed"] is True
    cases = f.client.get("/sales/pricing/floor-cases")
    assert cases.status_code == 200, cases.text
    row = cases.json()["items"][0]
    assert row["document_key"] == f.document_key and row["draft_version"] == 1
    assert row["gross_total_scr"] == "2200.00" and row["floor_line_count"] == 1
    assert len(row["pricing_fingerprint"]) == 64
    self_review = f.client.post(
        f"/sales/pricing/floor-cases/{f.case_key}/review", json={
            "operation_key": str(uuid4()), "expected_version": 1,
            "outcome": "APPROVED", "reason": "Self approval denied"})
    assert self_review.status_code == 403
    original = f.user.id; f.user.id = _reviewer(f).id
    try:
        approved = f.client.post(
            f"/sales/pricing/floor-cases/{f.case_key}/review", json={
                "operation_key": str(uuid4()), "expected_version": 1,
                "outcome": "APPROVED", "reason": "Exact pricing reviewed"})
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "APPROVED"
    finally:
        f.user.id = original
    assert f.db.query(ManagerCaseUse).join(ManagerCase,
        (ManagerCase.id == ManagerCaseUse.case_id) &
        (ManagerCase.org_id == ManagerCaseUse.org_id)).filter(
            ManagerCaseUse.org_id == f.org_a,
            ManagerCase.action == "sales.price-floor.approve").count() == 0
    assert f.client.get(f.url).json()["status"] == "DRAFT"


def test_changed_draft_invalidates_unreviewed_floor_case(floor_api):
    f = floor_api
    assert f.client.post("/sales/pricing/floor-cases", json=f.case_body).status_code == 200
    f.payload.update(operation_key=str(uuid4()), expected_version=1)
    f.payload["draft"]["lines"][0]["quantity"] = "3"
    assert f.client.put(f.url, json=f.payload).status_code == 200
    original = f.user.id; f.user.id = _reviewer(f).id
    try:
        response = f.client.post(
            f"/sales/pricing/floor-cases/{f.case_key}/review", json={
                "operation_key": str(uuid4()), "expected_version": 1,
                "outcome": "APPROVED", "reason": "Should be stale"})
        assert response.status_code == 409
        assert "changed" in response.json()["detail"].lower()
    finally:
        f.user.id = original


def test_floor_case_permissions_and_company_scope_are_fail_closed(floor_api):
    f = floor_api; policy = f.user.access_policy
    f.user.access_policy = replace(policy, permission_names=frozenset(
        f.permissions - {"Request_PriceFloorException"}))
    assert f.client.post("/sales/pricing/floor-cases", json=f.case_body).status_code == 403
    f.user.access_policy = replace(policy, permission_names=frozenset(
        f.permissions - {"Review_PriceFloorException"}))
    assert f.client.get("/sales/pricing/floor-cases?view=NEEDS_MY_REVIEW").status_code == 200
    f.user.access_policy = policy
    f.context.current_org_id = f.org_b
    f.context.allowed_org_ids = [f.org_a, f.org_b]
    f.context.is_root = True
    assert f.client.post("/sales/pricing/floor-cases", json=f.case_body).status_code == 404

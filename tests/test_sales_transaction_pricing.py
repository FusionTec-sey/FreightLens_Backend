"""Immutable T11 pricing inputs are exact, retry-safe and posting-effect free."""
from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

from Model.Credentials.users import User
from auth.policy import AccessPolicy
from tests.test_sales_intent_api import api  # noqa: F401
from tests.test_sales_intent_sources import source  # noqa: F401
from tests.test_policy_activation import activation  # noqa: F401
from tests.test_policy_manager_cases import policy_cases  # noqa: F401
from tests.test_inventory_policy_drafts import draft  # noqa: F401
from tests.test_inventory_locations import locations  # noqa: F401
from tests.test_sales_price_floor_cases import floor_api  # noqa: F401


def _approve(f, case_key):
    reviewer = User(org_id=f.org_a,
        username="pricing-snapshot-review-" + uuid4().hex[:16],
        password_hash="unusable-test-only")
    f.db.add(reviewer); f.db.commit()
    original = f.user.id; f.user.id = reviewer.id
    try:
        response = f.client.post(
            f"/sales/pricing/floor-cases/{case_key}/review", json={
                "operation_key": str(uuid4()), "expected_version": 1,
                "outcome": "APPROVED", "reason": "Exact synthetic pricing approved"})
        assert response.status_code == 200, response.text
    finally:
        f.user.id = original


def _prepare(f, operation_key, floor_case_key=None, version=1):
    return f.client.post(f"{f.url}/pricing-snapshots", json={
        "operation_key": str(operation_key),
        "expected_draft_version": version,
        "floor_case_key": (str(floor_case_key) if floor_case_key else None),
    })


def test_approved_exact_snapshot_is_immutable_retry_safe_and_not_a_sale(floor_api):
    from Model.containermgmt.Inventory.ManagerCase import ManagerCase, ManagerCaseUse
    from Model.containermgmt.Orders.SalesPricing import SalesTransactionPricing
    f = floor_api
    assert f.client.post("/sales/pricing/floor-cases", json=f.case_body).status_code == 200
    denied = _prepare(f, uuid4())
    assert denied.status_code == 403
    _approve(f, f.case_key)
    operation_key = uuid4()
    response = _prepare(f, operation_key, f.case_key)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["pricing_snapshot_key"] == str(operation_key)
    assert data["document_key"] == f.document_key
    assert data["draft_version"] == 1 and data["status"] == "PREPARED"
    assert data["gross_total_scr"] == "2200.00"
    assert Decimal(data["gross_total_scr"]) == (
        Decimal(data["net_total_scr"]) + Decimal(data["tax_total_scr"]))
    assert data["requires_floor_approval"] is True
    assert data["floor_case_key"] == str(f.case_key)
    assert data["posting_enabled"] is False
    assert len(data["pricing_fingerprint"]) == 64
    assert data["pricing"]["lines"][0]["selected_source"] == "CUSTOMER_AGREEMENT"
    assert data["pricing"]["lines"][0]["requires_floor_approval"] is True
    replay = _prepare(f, operation_key, f.case_key)
    assert replay.status_code == 200 and replay.json()["replayed"] is True
    assert f.db.query(SalesTransactionPricing).filter_by(
        org_id=f.org_a, document_key=f.document_key).count() == 1
    assert f.db.query(ManagerCaseUse).join(ManagerCase,
        (ManagerCase.id == ManagerCaseUse.case_id) &
        (ManagerCase.org_id == ManagerCaseUse.org_id)).filter(
            ManagerCase.org_id == f.org_a,
            ManagerCase.action == "sales.price-floor.approve").count() == 0
    latest = f.client.get(f"{f.url}/pricing-snapshots/latest?draft_version=1")
    assert latest.status_code == 200
    assert latest.json()["pricing_snapshot_key"] == str(operation_key)
    assert f.client.get(f.url).json()["status"] == "DRAFT"


def test_pending_wrong_or_stale_floor_inputs_fail_closed(floor_api):
    f = floor_api
    assert f.client.post("/sales/pricing/floor-cases", json=f.case_body).status_code == 200
    pending = _prepare(f, uuid4(), f.case_key)
    assert pending.status_code == 403
    assert _prepare(f, uuid4(), uuid4()).status_code == 403
    _approve(f, f.case_key)
    f.payload.update(operation_key=str(uuid4()), expected_version=1)
    f.payload["draft"]["lines"][0]["quantity"] = "3"
    assert f.client.put(f.url, json=f.payload).status_code == 200
    stale = _prepare(f, uuid4(), f.case_key, version=1)
    assert stale.status_code == 409
    changed = _prepare(f, uuid4(), f.case_key, version=2)
    assert changed.status_code == 409
    assert "exact pricing" in changed.json()["detail"].lower()


def test_snapshot_permissions_and_foreign_replay_are_denied(floor_api):
    f = floor_api
    assert f.client.post("/sales/pricing/floor-cases", json=f.case_body).status_code == 200
    _approve(f, f.case_key)
    operation_key = uuid4()
    policy = f.user.access_policy
    f.user.access_policy = replace(policy, permission_names=frozenset(
        f.permissions - {"Manage_SalesDraft"}))
    assert _prepare(f, operation_key, f.case_key).status_code == 403
    f.user.access_policy = policy
    assert _prepare(f, operation_key, f.case_key).status_code == 200
    f.context.current_org_id = f.org_b
    f.context.allowed_org_ids = [f.org_a, f.org_b]
    f.context.is_root = True
    assert _prepare(f, operation_key, f.case_key).status_code == 404
    assert f.client.get(f"{f.url}/pricing-snapshots/latest").status_code == 404

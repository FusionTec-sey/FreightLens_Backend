"""Protected paginated configuration API for synthetic T11 records."""
from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from auth.policy import AccessPolicy
from tests.test_sales_intent_api import api  # noqa: F401
from tests.test_sales_intent_sources import source  # noqa: F401
from tests.test_policy_activation import activation  # noqa: F401
from tests.test_policy_manager_cases import policy_cases  # noqa: F401
from tests.test_inventory_policy_drafts import draft  # noqa: F401
from tests.test_inventory_locations import locations  # noqa: F401


@pytest.fixture
def pricing_api(api):
    from Routes.Orders.SalesPricingRouter import SalesPricingRouter
    f = api; f.app.include_router(SalesPricingRouter)
    f.permissions |= {"View_Financials", "Manage_Financials"}
    f.user.access_policy = AccessPolicy(user=f.user, org_ids=(f.org_a,),
        permission_names=frozenset(f.permissions), module_names=frozenset({"SALES"}),
        field_permissions={"PERSONAL": "View_Personal_Data"})
    f.tax_key, f.price_key, f.assignment_key, f.agreement_key = (
        uuid4(), uuid4(), uuid4(), uuid4())
    f.tax_body = dict(operation_key=str(uuid4()), expected_version=0,
        code="VAT15", config=dict(name="Synthetic VAT", treatment="STANDARD",
            rate="0.15", is_enabled=True), reason="Synthetic API test")
    f.price_body = dict(operation_key=str(uuid4()), expected_version=0,
        branch_id=f.own, product_id=f.product.id, unit="BOX",
        config=dict(gross_unit_scr="1200", floor_gross_unit_scr="1000",
            is_enabled=True), reason="Synthetic API test")
    f.assignment_body = dict(operation_key=str(uuid4()), expected_version=0,
        product_id=f.product.id, tax_rule_key=str(f.tax_key), is_enabled=True,
        reason="Synthetic API test")
    f.agreement_body = dict(operation_key=str(uuid4()), expected_version=0,
        customer_key=str(f.customer_key), branch_id=f.own,
        product_id=f.product.id, unit="BOX",
        config=dict(gross_unit_scr="1100",
            valid_from=datetime(2020, 1, 1, tzinfo=timezone.utc).isoformat(),
            valid_until=None, terms_reference="Synthetic schedule",
            is_enabled=True), reason="Synthetic API test")
    return f


def put(f, kind, key, body):
    return f.client.put(f"/sales/pricing/{kind}/{key}", json=body)


def test_create_read_and_paginate_all_pricing_configuration(pricing_api):
    f = pricing_api
    for kind, key, body in [
        ("tax-rules", f.tax_key, f.tax_body),
        ("branch-prices", f.price_key, f.price_body),
        ("product-tax-assignments", f.assignment_key, f.assignment_body),
        ("customer-agreements", f.agreement_key, f.agreement_body),
    ]:
        response = put(f, kind, key, body)
        assert response.status_code == 200, response.text
        assert response.json()["version"] == 1
        assert f.client.get(f"/sales/pricing/{kind}/{key}").status_code == 200
        page = f.client.get(f"/sales/pricing/{kind}?limit=1")
        assert page.status_code == 200, page.text
        assert page.json()["total"] == 1 and page.json()["pages"] == 1
    assert f.client.get("/sales/pricing/branch-prices",
        params={"branch_id": f.own, "product_id": f.product.id,
                "unit": "BOX"}).json()["items"][0]["price_key"] == str(f.price_key)
    assert f.client.get("/sales/pricing/customer-agreements",
        params={"customer_key": str(f.customer_key), "unit": "BOX"}).json()["total"] == 1
    assert f.client.get("/sales/pricing/tax-rules?limit=101").status_code == 422


def test_replay_is_stable_changed_intent_conflicts_and_history_is_not_rewritten(pricing_api):
    f = pricing_api
    assert put(f, "tax-rules", f.tax_key, f.tax_body).status_code == 200
    assert put(f, "tax-rules", f.tax_key, f.tax_body).status_code == 200
    changed = {**f.tax_body, "config": {**f.tax_body["config"], "rate": "0.10"}}
    assert put(f, "tax-rules", f.tax_key, changed).status_code == 409
    update = {**f.tax_body, "operation_key": str(uuid4()),
        "expected_version": 1,
        "config": {**f.tax_body["config"], "rate": "0.10"}}
    response = put(f, "tax-rules", f.tax_key, update)
    assert response.status_code == 200 and response.json()["version"] == 2


def test_read_and_write_permissions_module_anonymous_and_foreign_scope(pricing_api):
    from auth.policy import get_request_policy
    f = pricing_api
    assert put(f, "branch-prices", f.price_key, f.price_body).status_code == 200
    policy = f.user.access_policy
    f.user.access_policy = replace(policy,
        permission_names=frozenset(f.permissions - {"Manage_Financials"}))
    assert f.client.get("/sales/pricing/branch-prices").status_code == 200
    assert put(f, "branch-prices", uuid4(),
        {**f.price_body, "operation_key": str(uuid4())}).status_code == 403
    f.user.access_policy = replace(policy, module_names=frozenset())
    assert f.client.get("/sales/pricing/branch-prices").status_code == 403
    f.user.access_policy = policy
    f.context.current_org_id = f.org_b
    f.context.allowed_org_ids = [f.org_a, f.org_b]
    f.context.is_root = True
    assert f.client.get("/sales/pricing/branch-prices").json()["items"] == []
    assert f.client.get(f"/sales/pricing/branch-prices/{f.price_key}").status_code == 404
    f.context.current_org_id = f.org_a
    for dependency in f.user_dependencies:
        f.app.dependency_overrides.pop(dependency)
    f.app.dependency_overrides.pop(get_request_policy, None)
    assert f.client.get("/sales/pricing/branch-prices").status_code == 401


def test_customer_agreements_require_personal_data_access(pricing_api):
    f = pricing_api
    f.user.access_policy = replace(f.user.access_policy, field_permissions={})
    assert f.client.get("/sales/pricing/customer-agreements").status_code == 403
    assert put(f, "customer-agreements", f.agreement_key,
        f.agreement_body).status_code == 403

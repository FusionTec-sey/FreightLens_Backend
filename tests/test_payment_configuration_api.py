"""T12A HTTP authorization, pagination and exact account isolation."""
from dataclasses import replace
from uuid import uuid4

import pytest
from auth.policy import AccessPolicy, get_request_policy
from Utils.migrate_20261005_payment_methods import ensure_payment_methods_schema
from Utils.migrate_20261005_branch_receiving_accounts import ensure_branch_receiving_accounts_schema
from tests.test_sales_intent_api import api  # noqa: F401
from tests.test_sales_intent_sources import source  # noqa: F401
from tests.test_policy_activation import activation  # noqa: F401
from tests.test_policy_manager_cases import policy_cases  # noqa: F401
from tests.test_inventory_policy_drafts import draft  # noqa: F401
from tests.test_inventory_locations import locations  # noqa: F401


@pytest.fixture
def payment_api(api):
    from Routes.Orders.PaymentConfigurationRouter import PaymentConfigurationRouter
    ensure_payment_methods_schema()
    ensure_branch_receiving_accounts_schema()
    f = api
    f.app.include_router(PaymentConfigurationRouter)
    f.permissions |= {"View_Financials", "Manage_Financials"}
    f.user.access_policy = AccessPolicy(user=f.user, org_ids=(f.org_a,),
        permission_names=frozenset(f.permissions), module_names=frozenset({"SALES"}),
        field_permissions={})
    f.method_key, f.mapping_key = uuid4(), uuid4()
    f.method_body = dict(operation_key=str(uuid4()), expected_version=0,
        code="SYNTH_CASH", config=dict(label="Synthetic cash", kind="CASH",
        is_enabled=True), reason="Synthetic test")
    f.mapping_body = dict(operation_key=str(uuid4()), expected_version=0,
        branch_id=f.own, method_key=str(f.method_key),
        config=dict(account_ref="SYNTH_LEDGER", label="Synthetic account",
                    is_enabled=True), reason="Synthetic test")
    return f


def test_payment_api_replay_lookup_and_permissions(payment_api):
    f = payment_api
    base = "/sales/payment-configuration"
    method = f.client.put(f"{base}/methods/{f.method_key}", json=f.method_body)
    assert method.status_code == 200, method.text
    replay = f.client.put(f"{base}/methods/{f.method_key}", json=f.method_body)
    assert replay.status_code == 200, replay.text
    assert replay.json()["replayed"] is True
    assert f.client.get(f"{base}/methods?limit=1").json()["total"] == 1
    assert f.client.get(f"{base}/methods?limit=101").status_code == 422
    params = dict(branch_id=f.own, method_key=str(f.method_key))
    assert f.client.get(f"{base}/receiving-account-lookup", params=params).json()[
        "reason"] == "MAPPING_MISSING"
    mapping = f.client.put(f"{base}/receiving-accounts/{f.mapping_key}",
                           json=f.mapping_body)
    assert mapping.status_code == 200, mapping.text
    resolved = f.client.get(f"{base}/receiving-account-lookup", params=params)
    assert resolved.status_code == 200 and resolved.json()["account_ref"] == "SYNTH_LEDGER"
    assert resolved.headers["cache-control"] == "private, no-store"
    assert f.client.get(f"{base}/receiving-accounts?branch_id={f.foreign}").status_code == 404
    policy = f.user.access_policy
    f.user.access_policy = replace(policy,
        permission_names=frozenset(f.permissions - {"Manage_Financials"}))
    assert f.client.get(f"{base}/methods").status_code == 200
    assert f.client.put(f"{base}/methods/{uuid4()}", json={
        **f.method_body, "operation_key": str(uuid4())}).status_code == 403
    f.user.access_policy = replace(policy, module_names=frozenset())
    assert f.client.get(f"{base}/methods").status_code == 403
    f.user.access_policy = policy
    f.context.current_org_id = f.org_b
    f.context.allowed_org_ids = [f.org_a, f.org_b]
    f.context.is_root = True
    assert f.client.get(f"{base}/methods").json()["items"] == []
    f.context.current_org_id = f.org_a
    for dependency in f.user_dependencies:
        f.app.dependency_overrides.pop(dependency)
    f.app.dependency_overrides.pop(get_request_policy, None)
    assert f.client.get(f"{base}/methods").status_code == 401

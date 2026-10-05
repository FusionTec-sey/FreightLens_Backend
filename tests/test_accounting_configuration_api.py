"""T20A HTTP authorization, pagination, replay, and tenant isolation."""
from dataclasses import replace
from uuid import uuid4

import pytest

from auth.policy import AccessPolicy, get_request_policy
from Utils.migrate_20261005_accounting_configuration import (
    ensure_accounting_configuration_schema,
)
from tests.test_sales_intent_api import api  # noqa: F401
from tests.test_sales_intent_sources import source  # noqa: F401
from tests.test_policy_activation import activation  # noqa: F401
from tests.test_policy_manager_cases import policy_cases  # noqa: F401
from tests.test_inventory_policy_drafts import draft  # noqa: F401
from tests.test_inventory_locations import locations  # noqa: F401


@pytest.fixture
def accounting_api(api):
    from Routes.Accounting.AccountingConfigurationRouter import (
        AccountingConfigurationRouter,
    )

    ensure_accounting_configuration_schema()
    f = api
    f.app.include_router(AccountingConfigurationRouter)
    f.permissions |= {"View_Financials", "Manage_Financials"}
    f.user.access_policy = AccessPolicy(
        user=f.user,
        org_ids=(f.org_a,),
        permission_names=frozenset(f.permissions),
        module_names=frozenset({"SALES"}),
        field_permissions={},
    )
    f.mapping_key = uuid4()
    f.body = {
        "operation_key": str(uuid4()),
        "expected_version": 0,
        "branch_id": f.own,
        "account_role": "SALES_REVENUE",
        "config": {
            "account_ref": "TEST.REVENUE",
            "label": "Test-only revenue",
            "is_enabled": True,
        },
        "reason": "Test-only configuration",
    }
    return f


def test_accounting_api_replay_paginated_reads_and_blocked_lookup(accounting_api):
    f = accounting_api
    base = "/accounting/configuration/account-mappings"
    missing = f.client.get(
        f"{base}/lookup",
        params={"branch_id": f.own, "account_role": "SALES_REVENUE"},
    )
    assert missing.status_code == 200
    assert missing.json()["reason"] == "MAPPING_MISSING"
    saved = f.client.put(f"{base}/{f.mapping_key}", json=f.body)
    assert saved.status_code == 200, saved.text
    replay = f.client.put(f"{base}/{f.mapping_key}", json=f.body)
    assert replay.status_code == 200 and replay.json()["replayed"] is True
    page = f.client.get(f"{base}?limit=1")
    assert page.status_code == 200
    assert page.json()["total"] == 1 and page.json()["limit"] == 1
    assert page.headers["cache-control"] == "private, no-store"
    assert f.client.get(f"{base}?limit=101").status_code == 422
    detail = f.client.get(f"{base}/{f.mapping_key}")
    assert detail.status_code == 200 and detail.json()["version"] == 1
    history = f.client.get(f"{base}/{f.mapping_key}/revisions?limit=1")
    assert history.status_code == 200 and history.json()["total"] == 1
    ready = f.client.get(
        f"{base}/lookup",
        params={"branch_id": f.own, "account_role": "SALES_REVENUE"},
    )
    assert ready.status_code == 200
    assert ready.json()["account_ref"] == "TEST.REVENUE"
    assert f.client.get(
        f"{base}/lookup",
        params={"branch_id": f.foreign, "account_role": "SALES_REVENUE"},
    ).status_code == 404


def test_accounting_api_permissions_module_stale_and_tenant_scope(accounting_api):
    f = accounting_api
    base = "/accounting/configuration/account-mappings"
    assert f.client.put(f"{base}/{f.mapping_key}", json=f.body).status_code == 200
    stale = {**f.body, "operation_key": str(uuid4())}
    assert f.client.put(f"{base}/{f.mapping_key}", json=stale).status_code == 409
    policy = f.user.access_policy
    f.user.access_policy = replace(
        policy,
        permission_names=frozenset(f.permissions - {"Manage_Financials"}),
    )
    assert f.client.get(base).status_code == 200
    assert f.client.put(
        f"{base}/{uuid4()}", json={**f.body, "operation_key": str(uuid4())}
    ).status_code == 403
    f.user.access_policy = replace(policy, module_names=frozenset())
    assert f.client.get(base).status_code == 403
    f.user.access_policy = policy
    f.context.current_org_id = f.org_b
    f.context.allowed_org_ids = [f.org_a, f.org_b]
    f.context.is_root = True
    assert f.client.get(base).json()["items"] == []
    assert f.client.get(f"{base}/{f.mapping_key}").status_code == 404
    f.context.current_org_id = f.org_a
    for dependency in f.user_dependencies:
        f.app.dependency_overrides.pop(dependency)
    f.app.dependency_overrides.pop(get_request_policy, None)
    assert f.client.get(base).status_code == 401

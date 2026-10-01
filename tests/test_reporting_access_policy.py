from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from reporting.policy import AccessPolicy


def _role(*permissions):
    return SimpleNamespace(
        permissions=[SimpleNamespace(name=name) for name in permissions],
    )


def _policy(roles_by_org, *, org_ids=(1,), platform_admin=False):
    return AccessPolicy.from_role_sets(
        user=SimpleNamespace(id=7, username="reporter", org_id=1),
        org_ids=org_ids,
        roles_by_org=roles_by_org,
        modules_by_org={org_id: ["ORDERS", "REPORTING"] for org_id in org_ids},
        field_permissions={
            "FINANCIAL": "View_Financials",
            "SUPPLIER_IDENTITY": "View_Supplier",
        },
        is_platform_admin=platform_admin,
    )


def test_single_org_policy_uses_only_roles_assigned_in_that_org():
    policy = _policy({1: [_role("View_Report", "View_Financials")]})

    assert policy.has("View_Report")
    assert policy.allows_field_class("FINANCIAL")
    assert not policy.allows_field_class("SUPPLIER_IDENTITY")


def test_cross_org_policy_intersects_permissions_and_modules():
    policy = AccessPolicy.from_role_sets(
        user=SimpleNamespace(id=7, username="reporter", org_id=1),
        org_ids=(1, 2),
        roles_by_org={
            1: [_role("View_Report", "View_Financials", "Cross_Org_Report")],
            2: [_role("View_Report", "Cross_Org_Report")],
        },
        modules_by_org={1: ["ORDERS", "REPORTING"], 2: ["REPORTING"]},
        field_permissions={"FINANCIAL": "View_Financials"},
    )

    assert policy.has("View_Report")
    assert policy.has("Cross_Org_Report")
    assert not policy.has("View_Financials")
    assert policy.module_names == frozenset({"REPORTING"})


def test_policy_denies_missing_permission_by_default():
    policy = _policy({1: []})

    with pytest.raises(HTTPException) as exc_info:
        policy.require_any("Run_Operational_Register", "View_Report")

    assert exc_info.value.status_code == 403


def test_compatibility_principal_contains_only_policy_permissions():
    policy = _policy({1: [_role("View_Report")]})

    permission_names = {
        permission.name
        for role in policy.scoped_user.roles
        for permission in role.permissions
    }
    assert permission_names == {"View_Report"}

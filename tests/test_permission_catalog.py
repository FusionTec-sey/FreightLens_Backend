import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from Routes.Creadentials.Credentials import _validate_org_scope
from Utils.org_filter import OrgContext
from auth.policy import AccessPolicy
from auth.policy.catalog import PERMISSION_BY_NAME, PLATFORM_PERMISSION_NAMES


def _called_permission_names() -> set[str]:
    names = set()
    for root in (Path("Routes"), Path("auth"), Path("reporting")):
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                function_name = (
                    node.func.id if isinstance(node.func, ast.Name)
                    else node.func.attr if isinstance(node.func, ast.Attribute)
                    else ""
                )
                if function_name not in {"has_permission", "require_permission", "require_any", "has"}:
                    continue
                for argument in node.args:
                    if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                        if "_" in argument.value and argument.value[0].isupper():
                            names.add(argument.value)
    return names


def test_every_permission_literal_used_by_guards_is_catalogued():
    assert _called_permission_names() - PERMISSION_BY_NAME.keys() == set()


def test_module_permission_does_not_count_when_module_is_disabled():
    role = SimpleNamespace(
        permissions=[SimpleNamespace(name="View_Order"), SimpleNamespace(name="View_Report")]
    )
    policy = AccessPolicy.from_role_sets(
        user=SimpleNamespace(id=1),
        org_ids=(1,),
        roles_by_org={1: [role]},
        modules_by_org={1: ["LOGISTICS"]},
        field_permissions={},
    )

    assert not policy.has("View_Order")
    assert policy.has("View_Report")


def test_tenant_admin_cannot_select_an_unassigned_organisation():
    policy = SimpleNamespace(is_platform_admin=False)
    context = OrgContext(current_org_id=7, allowed_org_ids=[7, 8], is_root=False)

    with pytest.raises(HTTPException) as exc_info:
        _validate_org_scope({7, 9}, policy, context)

    assert exc_info.value.status_code == 403


def test_platform_permissions_are_explicitly_classified():
    assert PLATFORM_PERMISSION_NAMES == {
        "View_TenantConsole", "Manage_TenantConsole"
    }

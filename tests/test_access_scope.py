import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from Utils.org_filter import OrgContext
from auth.dependencies import get_org_context
from auth.module_guard import require_module
from auth.policy import AccessPolicy
from auth.security_guards import (
    can_access_sourcing,
    can_view_supplier_user,
    has_permission,
    is_financial_user,
)


def _permission(name):
    return SimpleNamespace(name=name)


def _role(name, *permissions, is_platform_admin=False):
    return SimpleNamespace(
        name=name,
        permissions=[_permission(permission) for permission in permissions],
        is_platform_admin=is_platform_admin,
    )


def _user(*roles, org_id=1, allowed_org_ids=None):
    return SimpleNamespace(
        roles=list(roles),
        org_id=org_id,
        allowed_org_ids=allowed_org_ids,
    )


class _Query:
    def __init__(self, *, first=None, rows=None):
        self._first = first
        self._rows = rows or []

    def filter_by(self, **kwargs):
        return self

    def filter(self, *criteria):
        return self

    def first(self):
        return self._first

    def all(self):
        return self._rows


class _SequenceDb:
    def __init__(self, *queries):
        self._queries = iter(queries)

    def query(self, *entities):
        return next(self._queries)


def test_root_tenant_user_is_limited_to_explicit_assignments():
    user = _user(_role("Administrator"), allowed_org_ids=[1, 3])
    db = _SequenceDb(
        _Query(first=SimpleNamespace(id=1, is_active=True, parent_org_id=None)),
        _Query(rows=[(1,), (3,)]),
    )

    context = get_org_context(user=user, x_active_org=None, db=db)

    assert context.is_root is True
    assert context.allowed_org_ids == [1, 3]
    assert context.selected_org_id is None


def test_root_platform_admin_can_view_and_select_all_active_organisations():
    user = _user(_role("Platform Operations", is_platform_admin=True), allowed_org_ids=[1])
    db = _SequenceDb(
        _Query(first=SimpleNamespace(id=1, is_active=True, parent_org_id=None)),
        _Query(rows=[(1,), (7,), (8,)]),
        _Query(rows=[(1,), (7,), (8,)]),
    )

    context = get_org_context(user=user, x_active_org="8", db=db)

    assert context.allowed_org_ids == [1, 7, 8]
    assert context.selected_org_id == 8


def test_unassigned_active_organisation_selection_is_rejected():
    user = _user(_role("Administrator"), allowed_org_ids=[1, 3])
    db = _SequenceDb(
        _Query(first=SimpleNamespace(id=1, is_active=True, parent_org_id=None)),
        _Query(rows=[(1,), (3,)]),
    )

    with pytest.raises(HTTPException) as exc_info:
        get_org_context(user=user, x_active_org="2", db=db)

    assert exc_info.value.status_code == 403


def test_ordinary_administrator_has_no_implicit_permissions():
    assert not has_permission(_user(_role("Administrator")), "View_Financials")
    assert has_permission(
        _user(_role("Platform Operations", is_platform_admin=True)),
        "View_Financials",
    )


def test_sensitive_fields_require_explicit_permissions():
    buyer = _user(_role("buyer"))
    finance = _user(_role("finance", "View_Financials"))
    supplier_reader = _user(_role("buyer", "View_Supplier"))

    assert not is_financial_user(buyer)
    assert is_financial_user(finance)
    assert not can_view_supplier_user(buyer)
    assert can_view_supplier_user(supplier_reader)
    assert not can_access_sourcing(buyer, "Send_RFQ")


def test_module_guard_uses_selected_organisation_modules():
    user = _user(_role("Administrator"), org_id=1, allowed_org_ids=[1, 2])
    context = OrgContext(
        current_org_id=1,
        allowed_org_ids=[1, 2],
        is_root=True,
        selected_org_id=2,
    )
    db = _SequenceDb(
        _Query(rows=[SimpleNamespace(id=2, is_active=True, modules=["INVENTORY"])]),
    )
    policy = AccessPolicy(
        user=user,
        org_ids=(2,),
        permission_names=frozenset(),
        module_names=frozenset({"INVENTORY"}),
        field_permissions={},
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(require_module("ORDERS")(user, context, db, policy))

    assert exc_info.value.status_code == 403

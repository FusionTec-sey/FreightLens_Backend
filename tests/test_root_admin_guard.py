from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from Utils.org_filter import OrgContext
from auth.security_guards import require_admin, require_root_admin


def _user(*roles):
    return SimpleNamespace(roles=[SimpleNamespace(name=role) for role in roles])


def _context(is_root):
    return OrgContext(current_org_id=1, allowed_org_ids=[1], is_root=is_root)


def test_root_platform_administrator_is_allowed():
    user = _user("Super_Admin")
    assert require_root_admin(user, _context(True)) is user


def test_tenant_administrator_passes_admin_guard_without_root_privilege():
    user = _user("admin")
    assert require_admin(user) is user
    with pytest.raises(HTTPException):
        require_root_admin(user, _context(False))


@pytest.mark.parametrize(
    ("user", "context"),
    [
        (_user("Manager"), _context(True)),
        (_user("Administrator"), _context(True)),
        (_user("Administrator"), _context(False)),
        (_user(), _context(True)),
    ],
)
def test_non_root_or_non_admin_user_is_rejected(user, context):
    with pytest.raises(HTTPException) as exc_info:
        require_root_admin(user, context)
    assert exc_info.value.status_code == 403

from types import SimpleNamespace

from auth.policy import AccessPolicy
from auth.security_guards import has_permission, is_financial_user


def _policy(**overrides):
    values = {
        "user": SimpleNamespace(id=1),
        "org_ids": (1,),
        "permission_names": frozenset({"View_Order"}),
        "module_names": frozenset({"ORDERS"}),
        "field_permissions": {"FINANCIAL": "View_Financials"},
    }
    values.update(overrides)
    return AccessPolicy(**values)


def test_legacy_guards_use_attached_access_policy():
    user = SimpleNamespace(access_policy=_policy(), roles=[])
    assert has_permission(user, "View_Order") is True
    assert has_permission(user, "View_Financials") is False
    assert is_financial_user(user) is False


def test_financial_field_class_uses_same_permission_source():
    user = SimpleNamespace(
        access_policy=_policy(
            permission_names=frozenset({"View_Order", "View_Financials"})
        ),
        roles=[],
    )
    assert is_financial_user(user) is True


def test_access_endpoint_and_export_permission_are_explicit():
    auth_source = open("auth/routes.py", encoding="utf-8").read()
    report_source = open("Routes/Reports/ReportRouter.py", encoding="utf-8").read()
    assert '@router.get("/auth/me/access")' in auth_source
    assert report_source.count('require_any("Export_Report")') >= 2


def test_access_response_uses_authenticated_actor_identity():
    from auth.routes import get_my_access
    response = get_my_access(_policy(user=SimpleNamespace(id=72)))
    assert response['user_id'] == 72
    assert response['permissions'] == ['View_Order']
    assert 'username' not in response and 'password' not in response

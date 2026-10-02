from types import SimpleNamespace

from Model.containermgmt.Report.ReportTemplate import ReportTemplate
from Services import user_org_role_sync
from Utils import bootstrap_root_org
from auth.security_guards import is_platform_admin_user


def test_root_bootstrap_precedes_owner_backed_migrations():
    source = open("containerMgmt.py", encoding="utf-8").read()
    assert source.index("ensure_root_organisation()") < source.index(
        "ensure_report_templates_schema()"
    )
    assert "Bootstrapped root organisation id=1" in open(
        bootstrap_root_org.__file__, encoding="utf-8"
    ).read()


def test_report_template_type_has_database_default():
    assert ReportTemplate.__table__.c.template_type.server_default is not None


def test_platform_admin_requires_explicit_role_flag():
    named_only = SimpleNamespace(
        roles=[SimpleNamespace(name="super_admin", is_platform_admin=False)]
    )
    renamed_flagged = SimpleNamespace(
        roles=[SimpleNamespace(name="Operations", is_platform_admin=True)]
    )
    assert is_platform_admin_user(named_only) is False
    assert is_platform_admin_user(renamed_flagged) is True


def test_user_org_role_sync_is_transactional_bridge():
    source = open(user_org_role_sync.__file__, encoding="utf-8").read()
    assert "delete(user_org_roles)" in source
    assert "insert(user_org_roles)" in source

"""Three-state field access: hidden, read-only, editable.

These are pure policy tests -- no database -- so they run without the Postgres
fixture the integration suite needs.
"""

from types import SimpleNamespace

from auth.policy import AccessPolicy
from auth.policy.field_registry import (
    FIELD_CLASS_BY_CODE,
    FIELD_CLASS_SPECS,
    field_class_for,
    partition_by_mode,
)
from auth.policy.catalog import PERMISSION_BY_NAME

VIEW_PERMISSIONS = {code: spec["view"] for code, spec in FIELD_CLASS_BY_CODE.items()}
EDIT_PERMISSIONS = {code: spec["edit"] for code, spec in FIELD_CLASS_BY_CODE.items()}


def _role(*permissions):
    return SimpleNamespace(
        permissions=[SimpleNamespace(name=name) for name in permissions],
    )


def _policy(*permissions, platform_admin=False, field_edit_permissions=None):
    return AccessPolicy.from_role_sets(
        user=SimpleNamespace(id=7, username="ops", org_id=1),
        org_ids=(1,),
        roles_by_org={1: [_role(*permissions)]},
        modules_by_org={1: ["LOGISTICS", "ORDERS", "REPORTING"]},
        field_permissions={**VIEW_PERMISSIONS, "FINANCIAL": "View_Financials"},
        field_edit_permissions=(
            EDIT_PERMISSIONS if field_edit_permissions is None else field_edit_permissions
        ),
        is_platform_admin=platform_admin,
    )


def test_holding_neither_permission_hides_the_class():
    policy = _policy("View_Container")

    assert policy.field_mode("CONTAINER_TAX") == "hidden"
    assert not policy.allows_field_class("CONTAINER_TAX")
    assert not policy.allows_field_write("CONTAINER_TAX")


def test_view_permission_alone_is_read_only():
    policy = _policy("View_Demurrage")

    assert policy.field_mode("CONTAINER_DEMURRAGE") == "read"
    assert policy.allows_field_class("CONTAINER_DEMURRAGE")
    assert not policy.allows_field_write("CONTAINER_DEMURRAGE")


def test_edit_permission_implies_viewing():
    """Nothing should be editable but invisible, even without the view name."""
    policy = _policy("Edit_ContainerNote")

    assert policy.field_mode("CONTAINER_NOTE") == "edit"
    assert policy.allows_field_class("CONTAINER_NOTE")
    assert policy.allows_field_write("CONTAINER_NOTE")


def test_unclassified_fields_stay_open():
    policy = _policy("View_Container")

    assert field_class_for("container", "status") is None
    assert policy.field_mode(None) == "edit"
    writable, refused = partition_by_mode(policy, "container", ["status", "type"])
    assert writable == ["status", "type"]
    assert refused == []


def test_platform_admin_bypasses_every_class():
    policy = _policy(platform_admin=True)

    for code in FIELD_CLASS_BY_CODE:
        assert policy.field_mode(code) == "edit"


def test_reporting_classes_keep_read_only_semantics():
    """A class with no edit permission must not become un-writable by accident.

    The reporting classes only ever redact, so allows_field_class -- which the
    report compiler and the dashboard registry both call -- has to behave
    exactly as it did before edit permissions existed.
    """
    policy = _policy("View_Financials", field_edit_permissions={})

    assert policy.allows_field_class("FINANCIAL") is True
    assert policy.field_mode("FINANCIAL") == "edit"
    assert policy.allows_field_class("SUPPLIER_IDENTITY") is False


def test_unknown_class_is_refused_not_ignored():
    policy = _policy("View_Container")

    assert policy.field_mode("NOT_A_REAL_CLASS") == "hidden"
    assert not policy.allows_field_class("NOT_A_REAL_CLASS")


def test_partition_splits_a_container_payload_by_mode():
    """The reduced container view: tax and number hidden, free days locked."""
    policy = _policy(
        "View_Demurrage",
        "Edit_ContainerMilestone",
        "Edit_Material",
        "Edit_ContainerNote",
    )

    writable, refused = partition_by_mode(
        policy,
        "container",
        ["container_no", "tax", "FreeDays", "in_bound", "materials", "note", "status"],
    )

    assert writable == ["in_bound", "materials", "note", "status"]
    assert refused == ["container_no", "tax", "FreeDays"]


def test_nested_bill_of_lading_keys_are_gated():
    policy = _policy("View_Demurrage")

    _, refused = partition_by_mode(
        policy, "container", ["bill_of_landing.FreeDays"]
    )
    assert refused == ["bill_of_landing.FreeDays"]


def test_every_declared_field_permission_is_catalogued():
    """from_role_sets drops names the catalog does not declare, so a missing
    entry would silently deny the class forever -- which is what happened to
    PERSONAL/View_Personal_Data."""
    for code, view, edit, _description in FIELD_CLASS_SPECS:
        assert view in PERMISSION_BY_NAME, f"{code} view permission not catalogued"
        assert edit in PERMISSION_BY_NAME, f"{code} edit permission not catalogued"

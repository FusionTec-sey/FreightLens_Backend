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
from auth.policy.catalog import PERMISSION_BY_NAME, derived_view_names

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
    """Every field on the container tab is classified now, so this uses B/L
    fields, which carry their own guards rather than a field class."""
    policy = _policy("View_Container")

    assert field_class_for("container", "bill_of_landing.Vessel") is None
    assert policy.field_mode(None) == "edit"
    writable, refused = partition_by_mode(
        policy, "container", ["bill_of_landing.Vessel", "not_a_registered_field"]
    )
    assert writable == ["bill_of_landing.Vessel", "not_a_registered_field"]
    assert refused == []


def test_status_is_gated_on_both_the_container_and_the_bill_of_lading():
    """Setting status on a B/L cascades to every container on it, so gating the
    container field alone would leave the cascade as a way round it."""
    assert field_class_for("container", "status") == "CONTAINER_STATUS"
    assert field_class_for("container", "bill_of_landing.status") == "CONTAINER_STATUS"

    locked = _policy("View_Status")
    assert locked.field_mode("CONTAINER_STATUS") == "read"
    _, refused = partition_by_mode(
        locked, "container", ["status", "bill_of_landing.status"]
    )
    assert refused == ["status", "bill_of_landing.status"]

    allowed = _policy("Edit_Status")
    writable, refused = partition_by_mode(
        allowed, "container", ["status", "bill_of_landing.status"]
    )
    assert writable == ["status", "bill_of_landing.status"]
    assert refused == []


def test_every_date_field_is_covered_by_the_milestone_class():
    for key in (
        "in_bound", "out_bound", "unloaded_at_port", "empty_date",
        "emptied_at", "bill_of_landing.ArrivalDate",
    ):
        assert field_class_for("container", key) == "CONTAINER_MILESTONE", key


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
        "Edit_Status",
        "Edit_ContainerType",
    )

    writable, refused = partition_by_mode(
        policy,
        "container",
        ["container_no", "tax", "FreeDays", "in_bound", "materials", "note",
         "type", "status"],
    )

    assert writable == ["in_bound", "materials", "note", "type", "status"]
    assert refused == ["container_no", "tax", "FreeDays"]


def test_nested_bill_of_lading_keys_are_gated():
    policy = _policy("View_Demurrage")

    _, refused = partition_by_mode(
        policy, "container", ["bill_of_landing.FreeDays"]
    )
    assert refused == ["bill_of_landing.FreeDays"]


def test_edit_implies_view_on_the_policy_itself():
    """The rule has to hold on AccessPolicy.has, not only in the legacy role
    walk. Container routes now depend on get_request_policy, and before this
    the implication silently vanished the moment a policy was attached -- the
    same user passing a check on one route and failing it on another."""
    policy = _policy("Edit_Container")

    assert policy.has("Edit_Container")
    assert policy.has("View_Container")
    assert policy.has_any("View_Container")


def test_add_and_delete_also_imply_view():
    assert _policy("Add_Order").has("View_Order")
    assert _policy("Delete_Order").has("View_Order")


def test_implication_only_runs_one_way():
    """View_X must never grant Edit_X, or read-only access would not exist."""
    policy = _policy("View_Container")

    assert policy.has("View_Container")
    assert not policy.has("Edit_Container")
    assert not policy.has("Delete_Container")


def test_implication_is_limited_to_catalogued_names():
    policy = _policy("Edit_Container")

    assert derived_view_names("View_NotARealResource") == ()
    assert not policy.has("View_NotARealResource")


def test_manage_does_not_imply_view():
    """The frontend offers Manage_ as a convenience when granting, but making
    it imply viewing server-side would widen access to priced data."""
    assert "Manage_Financials" not in derived_view_names("View_Financials")
    assert not _policy("Manage_Financials").has("View_Financials")


def test_every_field_class_edit_permission_implies_its_view_permission():
    """A role granted only the edit half must still resolve to edit mode, and
    must satisfy any plain View_ check elsewhere in the codebase."""
    for code, view, edit, _description in FIELD_CLASS_SPECS:
        policy = _policy(edit)
        assert policy.field_mode(code) == "edit", code
        assert policy.has(view), f"{edit} should imply {view}"


def test_every_declared_field_permission_is_catalogued():
    """from_role_sets drops names the catalog does not declare, so a missing
    entry would silently deny the class forever -- which is what happened to
    PERSONAL/View_Personal_Data."""
    for code, view, edit, _description in FIELD_CLASS_SPECS:
        assert view in PERMISSION_BY_NAME, f"{code} view permission not catalogued"
        assert edit in PERMISSION_BY_NAME, f"{code} edit permission not catalogued"

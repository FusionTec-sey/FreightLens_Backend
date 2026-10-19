from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Iterable, Literal, Mapping, Sequence

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from Model.Credentials.Organisation import Organisation
from Model.Credentials.roles import Role
from Model.Credentials.user_org_roles import user_org_roles
from Model.Credentials.users import User
from Model.containermgmt.Report.ReportFieldClass import ReportFieldClass
from Model.db import get_db
from Utils.org_filter import OrgContext
from auth.dependencies import get_current_user, get_org_context
from .catalog import PERMISSION_BY_NAME, derived_view_names

FieldMode = Literal["hidden", "read", "edit"]


@dataclass(frozen=True)
class AccessPolicy:
    user: User
    org_ids: tuple[int, ...]
    permission_names: frozenset[str]
    module_names: frozenset[str]
    field_permissions: Mapping[str, str]
    is_platform_admin: bool = False
    location_ids: tuple[int, ...] = ()
    # field class code -> permission that grants editing, where the class has one.
    field_edit_permissions: Mapping[str, str] = field(default_factory=dict)

    def has(self, permission_name: str) -> bool:
        """Whether this policy grants a permission, directly or by implication.

        Edit_X, Add_X and Delete_X each imply View_X: nothing is editable but
        invisible. The legacy role walk in security_guards and the page registry
        have always applied this, but it was lost the moment a request had an
        AccessPolicy attached, because this method only matched exact names --
        so the same user could pass a check on one route and fail it on another.
        """
        if self.is_platform_admin or permission_name in self.permission_names:
            return True
        return any(
            name in self.permission_names
            for name in derived_view_names(permission_name)
        )

    def has_any(self, *permission_names: str) -> bool:
        return any(self.has(name) for name in permission_names)

    def allows_field_class(self, field_class: str | None) -> bool:
        return self.field_mode(field_class) != "hidden"

    def field_mode(self, field_class: str | None) -> FieldMode:
        """How much of a field class this policy may see: hidden, read or edit.

        Editing is a second permission on the same class rather than a separate
        mode flag, so granting it is the ordinary role-permission screen. Holding
        the edit permission implies reading -- nothing is editable but invisible
        -- which this resolves explicitly rather than relying on the implicit-view
        rule in security_guards, since AccessPolicy.has does not apply it.

        An unclassified field is open, matching how unclassified report columns
        have always behaved. A class that is known but unmapped stays hidden.
        """
        if not field_class:
            return "edit"
        code = field_class.upper()
        edit_permission = self.field_edit_permissions.get(code)
        if edit_permission and self.has(edit_permission):
            return "edit"
        view_permission = self.field_permissions.get(code)
        if view_permission and self.has(view_permission):
            # A class with no edit permission is read-only by definition: that is
            # every reporting class, which only ever redacts.
            return "read" if edit_permission else "edit"
        return "hidden"

    def allows_field_write(self, field_class: str | None) -> bool:
        return self.field_mode(field_class) == "edit"

    def require_any(self, *permission_names: str) -> None:
        if not self.has_any(*permission_names):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required permission: {' or '.join(permission_names)}",
            )

    @property
    def scoped_user(self):
        permissions = [SimpleNamespace(name=name) for name in sorted(self.permission_names)]
        role = SimpleNamespace(
            name="access_policy",
            permissions=permissions,
            is_platform_admin=self.is_platform_admin,
        )
        return SimpleNamespace(
            id=getattr(self.user, "id", None),
            username=getattr(self.user, "username", None),
            org_id=getattr(self.user, "org_id", None),
            allowed_org_ids=list(self.org_ids),
            roles=[role],
            access_policy=self,
        )

    @classmethod
    def from_role_sets(
        cls,
        *,
        user: User,
        org_ids: Sequence[int],
        roles_by_org: Mapping[int, Iterable[Role]],
        modules_by_org: Mapping[int, Iterable[str]],
        field_permissions: Mapping[str, str],
        is_platform_admin: bool = False,
        field_edit_permissions: Mapping[str, str] | None = None,
    ) -> "AccessPolicy":
        permission_sets = []
        module_sets = []
        for org_id in org_ids:
            permission_sets.append({
                permission.name
                for role in roles_by_org.get(org_id, ())
                for permission in getattr(role, "permissions", ())
            })
            module_sets.append(set(modules_by_org.get(org_id, ())))
        permissions = set.intersection(*permission_sets) if permission_sets else set()
        modules = set.intersection(*module_sets) if module_sets else set()
        permissions = {
            name for name in permissions
            if name in PERMISSION_BY_NAME
            and (
                PERMISSION_BY_NAME[name].module is None
                or PERMISSION_BY_NAME[name].module in modules
            )
        }
        return cls(
            user=user,
            org_ids=tuple(org_ids),
            permission_names=frozenset(permissions),
            module_names=frozenset(modules),
            field_permissions={key.upper(): value for key, value in field_permissions.items()},
            is_platform_admin=is_platform_admin,
            field_edit_permissions={
                key.upper(): value
                for key, value in (field_edit_permissions or {}).items()
                if value
            },
        )


def _build_policy(db: Session, user: User, org_ids: Sequence[int]) -> AccessPolicy:
    role_rows = (
        db.query(user_org_roles.c.org_id, Role)
        .join(Role, Role.id == user_org_roles.c.role_id)
        .filter(
            user_org_roles.c.user_id == user.id,
            user_org_roles.c.org_id.in_(org_ids),
            Role.is_deleted.is_(False),
        )
        .all()
    )
    roles_by_org = {org_id: [] for org_id in org_ids}
    for org_id, role in role_rows:
        roles_by_org[org_id].append(role)
    organisations = db.query(Organisation).filter(Organisation.id.in_(org_ids)).all()
    modules_by_org = {org.id: (org.modules or []) for org in organisations}
    field_class_rows = db.query(ReportFieldClass).all()
    field_permissions = {row.code: row.permission_name for row in field_class_rows}
    field_edit_permissions = {
        row.code: row.edit_permission_name
        for row in field_class_rows
        if row.edit_permission_name
    }
    policy = AccessPolicy.from_role_sets(
        user=user,
        org_ids=org_ids,
        roles_by_org=roles_by_org,
        modules_by_org=modules_by_org,
        field_permissions=field_permissions,
        field_edit_permissions=field_edit_permissions,
        is_platform_admin=any(
            bool(getattr(role, "is_platform_admin", False))
            for role in getattr(user, "roles", ())
        ),
    )
    user.access_policy = policy
    return policy


def get_access_policy(
    user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
) -> AccessPolicy:
    org_ids = (
        [org_context.selected_org_id]
        if org_context.selected_org_id is not None
        else list(org_context.allowed_org_ids)
    )
    policy = _build_policy(db, user, org_ids)
    if len(org_ids) > 1 and not policy.has("Cross_Org_Report"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cross-organisation reporting requires Cross_Org_Report",
        )
    return policy


def get_request_policy(
    user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
) -> AccessPolicy:
    """Build the active-org policy once for non-reporting request guards."""
    org_id = org_context.selected_org_id or org_context.current_org_id
    return _build_policy(db, user, [org_id])

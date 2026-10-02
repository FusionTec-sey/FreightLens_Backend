from datetime import datetime
from types import SimpleNamespace

from fastapi import Depends, HTTPException, status
from fastapi_utils.cbv import cbv
from fastapi_utils.inferring_router import InferringRouter
from sqlalchemy import delete, insert, or_, select
from sqlalchemy.orm import Session, joinedload

from Model import Organisation, Permission, Role, User
from Model.Credentials.user_org_roles import user_org_roles
from Model.db import get_db
from Schema import RoleBase, UserBase
from Schema.Credentials.user import UserOrgRolesUpdate
from Utils.org_filter import OrgContext
from auth.dependencies import get_current_user, get_org_context
from auth.policy import AccessPolicy, get_request_policy
from auth.policy.catalog import PLATFORM_PERMISSION_NAMES
from auth.security import hash_password

CreadentialsInfo = InferringRouter()


def _require(policy: AccessPolicy, permission: str) -> None:
    if not policy.has(permission):
        raise HTTPException(status_code=403, detail=f"Missing required permission: {permission}")


def _validate_org_scope(org_ids: set[int], policy: AccessPolicy, context: OrgContext) -> None:
    if not org_ids or None in org_ids:
        raise HTTPException(status_code=422, detail="At least one organisation is required")
    unavailable = org_ids - set(context.allowed_org_ids)
    if unavailable:
        raise HTTPException(
            status_code=403,
            detail=f"Cannot manage unassigned organisation(s): {sorted(unavailable)}",
        )


def _load_roles(
    db: Session, role_ids: set[int], org_ids: set[int], policy: AccessPolicy
) -> dict[int, Role]:
    roles = (
        db.query(Role)
        .options(joinedload(Role.permissions))
        .filter(Role.id.in_(role_ids), Role.is_deleted.is_(False))
        .all()
        if role_ids else []
    )
    if len(roles) != len(role_ids):
        raise HTTPException(status_code=422, detail="One or more roles do not exist")
    for role in roles:
        if role.org_id is not None and role.org_id not in org_ids:
            raise HTTPException(status_code=403, detail=f"Role '{role.name}' belongs to another organisation")
        if not policy.is_platform_admin and (
            role.is_platform_admin
            or any(p.name in PLATFORM_PERMISSION_NAMES for p in role.permissions)
        ):
            raise HTTPException(status_code=403, detail="Platform authority cannot be delegated by a tenant admin")
    return {role.id: role for role in roles}


def _replace_org_roles(
    db: Session,
    user: User,
    assignments: list,
    policy: AccessPolicy,
    context: OrgContext,
) -> None:
    org_ids = {assignment.org_id for assignment in assignments}
    _validate_org_scope(org_ids, policy, context)
    active_org_ids = {
        row[0] for row in db.execute(
            select(Organisation.id).where(
                Organisation.id.in_(org_ids), Organisation.is_active.is_(True)
            )
        )
    }
    if active_org_ids != org_ids:
        raise HTTPException(status_code=422, detail="Every assigned organisation must be active")

    role_ids = {role_id for assignment in assignments for role_id in assignment.role_ids}
    roles = _load_roles(db, role_ids, org_ids, policy)
    rows = []
    for assignment in assignments:
        for role_id in dict.fromkeys(assignment.role_ids):
            role = roles[role_id]
            if role.org_id is not None and role.org_id != assignment.org_id:
                raise HTTPException(status_code=403, detail=f"Role '{role.name}' cannot be assigned in this organisation")
            rows.append({"user_id": user.id, "org_id": assignment.org_id, "role_id": role_id})

    db.execute(delete(user_org_roles).where(user_org_roles.c.user_id == user.id))
    if rows:
        db.execute(insert(user_org_roles), rows)
    ordered_org_ids = sorted(org_ids)
    user.allowed_org_ids = ordered_org_ids
    if user.org_id not in org_ids:
        user.org_id = ordered_org_ids[0]
    # Compatibility projection for existing token claims; authorization reads
    # user_org_roles through AccessPolicy for the active organisation.
    user.roles = list(roles.values())


def _assignments(db: Session, user_ids: list[int]) -> dict[int, list[dict]]:
    rows = db.execute(
        select(user_org_roles.c.user_id, user_org_roles.c.org_id, user_org_roles.c.role_id)
        .where(user_org_roles.c.user_id.in_(user_ids))
        .order_by(user_org_roles.c.user_id, user_org_roles.c.org_id, user_org_roles.c.role_id)
    ).all() if user_ids else []
    grouped: dict[int, dict[int, list[int]]] = {}
    for user_id, org_id, role_id in rows:
        grouped.setdefault(user_id, {}).setdefault(org_id, []).append(role_id)
    return {
        user_id: [{"org_id": org_id, "role_ids": role_ids} for org_id, role_ids in orgs.items()]
        for user_id, orgs in grouped.items()
    }


def _serialize_user(user: User, names: dict[int, str], assignments: list[dict]) -> dict:
    org_ids = [assignment["org_id"] for assignment in assignments]
    return {
        "id": user.id,
        "username": user.username,
        "org_id": user.org_id,
        "org_ids": org_ids,
        "org_name": names.get(user.org_id, f"Org #{user.org_id}"),
        "org_names": [names.get(org_id, f"Org #{org_id}") for org_id in org_ids],
        "roles": sorted({role.name for role in user.roles}),
        "org_roles": assignments,
    }


def _complete_assignments(user: User, assignments: list[dict]) -> list[dict]:
    by_org = {assignment["org_id"]: assignment for assignment in assignments}
    for org_id in user.allowed_org_ids or ([user.org_id] if user.org_id else []):
        by_org.setdefault(org_id, {"org_id": org_id, "role_ids": []})
    return [by_org[org_id] for org_id in sorted(by_org)]


def _legacy_assignments(org_ids: list[int], role_ids: list[int]) -> list[SimpleNamespace]:
    return [SimpleNamespace(org_id=org_id, role_ids=role_ids) for org_id in org_ids]


@cbv(CreadentialsInfo)
class CreadentialsInfoAPI:
    @CreadentialsInfo.get("/getRole")
    @CreadentialsInfo.get("/getRoles")
    async def get_roles(
        self,
        db: Session = Depends(get_db),
        policy: AccessPolicy = Depends(get_request_policy),
        context: OrgContext = Depends(get_org_context),
    ):
        _require(policy, "View_Role")
        active_org = context.selected_org_id or context.current_org_id
        roles = (
            db.query(Role).options(joinedload(Role.permissions))
            .filter(Role.is_deleted.is_(False), or_(Role.org_id.is_(None), Role.org_id == active_org))
            .all()
        )
        if not policy.is_platform_admin:
            roles = [
                role for role in roles
                if not role.is_platform_admin
                and not any(
                    permission.name in PLATFORM_PERMISSION_NAMES
                    for permission in role.permissions
                )
            ]
        return [{
            "id": role.id, "name": role.name, "org_id": role.org_id,
            "is_platform_admin": role.is_platform_admin,
            "permissions": [permission.id for permission in role.permissions],
        } for role in roles]

    @CreadentialsInfo.get("/getUser")
    @CreadentialsInfo.get("/getUsers")
    async def get_users(
        self,
        db: Session = Depends(get_db),
        policy: AccessPolicy = Depends(get_request_policy),
        context: OrgContext = Depends(get_org_context),
    ):
        _require(policy, "View_User")
        visible_orgs = set(context.allowed_org_ids)
        users = db.query(User).filter(User.is_deleted.is_(False)).options(joinedload(User.roles)).all()
        assignment_map = _assignments(db, [user.id for user in users])
        assignment_map = {
            user.id: _complete_assignments(user, assignment_map.get(user.id, []))
            for user in users
        }
        users = [
            user for user in users
            if visible_orgs.intersection(a["org_id"] for a in assignment_map.get(user.id, []))
        ]
        names = {
            org.id: org.display_name or org.name
            for org in db.query(Organisation).filter(Organisation.id.in_(visible_orgs)).all()
        }
        return [_serialize_user(user, names, assignment_map.get(user.id, [])) for user in users]

    @CreadentialsInfo.get("/getPermission")
    @CreadentialsInfo.get("/getRolePermissions")
    @CreadentialsInfo.get("/getPermissions")
    async def get_permissions(
        self,
        db: Session = Depends(get_db),
        policy: AccessPolicy = Depends(get_request_policy),
    ):
        _require(policy, "View_Role")
        permissions = db.query(Permission).order_by(Permission.name).all()
        if not policy.is_platform_admin:
            permissions = [p for p in permissions if p.name not in PLATFORM_PERMISSION_NAMES]
        return [{"id": p.id, "name": p.name, "description": p.description, "descriptionp": p.description} for p in permissions]

    @CreadentialsInfo.get("/getOrganisations")
    async def get_organisations(
        self,
        db: Session = Depends(get_db),
        policy: AccessPolicy = Depends(get_request_policy),
        context: OrgContext = Depends(get_org_context),
    ):
        _require(policy, "View_User")
        orgs = db.query(Organisation).filter(
            Organisation.id.in_(context.allowed_org_ids), Organisation.is_active.is_(True)
        ).all()
        return [{"id": org.id, "name": org.name, "display_name": org.display_name or org.name} for org in orgs]

    @CreadentialsInfo.post("/addPermission")
    @CreadentialsInfo.post("/addRole")
    async def add_role(
        self,
        payload: RoleBase,
        db: Session = Depends(get_db),
        policy: AccessPolicy = Depends(get_request_policy),
        context: OrgContext = Depends(get_org_context),
    ):
        _require(policy, "Add_Role")
        org_id = payload.org_id or context.selected_org_id or context.current_org_id
        _validate_org_scope({org_id}, policy, context)
        permissions = db.query(Permission).filter(Permission.id.in_(payload.permissions or [])).all()
        if not policy.is_platform_admin and any(p.name in PLATFORM_PERMISSION_NAMES for p in permissions):
            raise HTTPException(status_code=403, detail="Platform permissions cannot be granted by a tenant admin")
        role = Role(name=payload.name, org_id=org_id, permissions=permissions)
        db.add(role)
        db.commit()
        db.refresh(role)
        return {"id": role.id, "name": role.name, "org_id": role.org_id, "permissions": [{"id": p.id, "name": p.name} for p in role.permissions]}

    @CreadentialsInfo.post("/addUser")
    async def add_user(
        self,
        payload: UserBase,
        db: Session = Depends(get_db),
        policy: AccessPolicy = Depends(get_request_policy),
        context: OrgContext = Depends(get_org_context),
    ):
        _require(policy, "Add_User")
        username = payload.username or payload.name
        if not username or not payload.password:
            raise HTTPException(status_code=422, detail="Username and password are required")
        if db.query(User).filter(User.username == username, User.is_deleted.is_(False)).first():
            raise HTTPException(status_code=400, detail="Username already exists")
        org_ids = payload.org_ids or ([payload.org_id] if payload.org_id else [context.selected_org_id or context.current_org_id])
        role_ids = [role for role in (payload.roles or []) if isinstance(role, int)]
        assignments = payload.org_roles or _legacy_assignments(org_ids, role_ids)
        user = User(username=username, password_hash=hash_password(payload.password), org_id=org_ids[0], allowed_org_ids=org_ids)
        db.add(user)
        db.flush()
        _replace_org_roles(db, user, assignments, policy, context)
        db.commit()
        db.refresh(user)
        data = _complete_assignments(user, _assignments(db, [user.id]).get(user.id, []))
        names = {org.id: org.display_name or org.name for org in db.query(Organisation).filter(Organisation.id.in_(org_ids)).all()}
        return _serialize_user(user, names, data)

    @CreadentialsInfo.put("/users/{user_id}/org-roles")
    async def update_user_org_roles(
        self,
        user_id: int,
        payload: UserOrgRolesUpdate,
        db: Session = Depends(get_db),
        policy: AccessPolicy = Depends(get_request_policy),
        context: OrgContext = Depends(get_org_context),
    ):
        _require(policy, "Edit_User")
        user = db.query(User).filter(User.id == user_id, User.is_deleted.is_(False)).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        existing = _complete_assignments(user, _assignments(db, [user.id]).get(user.id, []))
        _validate_org_scope({a["org_id"] for a in existing} or {user.org_id}, policy, context)
        _replace_org_roles(db, user, payload.assignments, policy, context)
        db.commit()
        data = _complete_assignments(user, _assignments(db, [user.id]).get(user.id, []))
        return {"user_id": user.id, "assignments": data}

    @CreadentialsInfo.put("/updateUser/{user_id}")
    async def update_user(
        self,
        user_id: int,
        payload: UserBase,
        db: Session = Depends(get_db),
        policy: AccessPolicy = Depends(get_request_policy),
        context: OrgContext = Depends(get_org_context),
    ):
        _require(policy, "Edit_User")
        user = db.query(User).filter(User.id == user_id, User.is_deleted.is_(False)).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        existing = _complete_assignments(user, _assignments(db, [user.id]).get(user.id, []))
        _validate_org_scope({a["org_id"] for a in existing} or {user.org_id}, policy, context)
        if payload.username or payload.name:
            user.username = payload.username or payload.name
        if payload.password:
            user.password_hash = hash_password(payload.password)
        if payload.org_ids is not None or payload.org_id is not None or payload.roles is not None:
            org_ids = payload.org_ids or ([payload.org_id] if payload.org_id else [a["org_id"] for a in existing])
            role_ids = [role for role in (payload.roles or []) if isinstance(role, int)]
            _replace_org_roles(db, user, _legacy_assignments(org_ids, role_ids), policy, context)
        db.commit()
        db.refresh(user)
        data = _complete_assignments(user, _assignments(db, [user.id]).get(user.id, []))
        names = {org.id: org.display_name or org.name for org in db.query(Organisation).filter(Organisation.id.in_(user.allowed_org_ids)).all()}
        return _serialize_user(user, names, data)

    @CreadentialsInfo.delete("/deleteUser/{user_id}")
    async def delete_user(
        self,
        user_id: int,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
        policy: AccessPolicy = Depends(get_request_policy),
        context: OrgContext = Depends(get_org_context),
    ):
        _require(policy, "Delete_User")
        user = db.query(User).filter(User.id == user_id, User.is_deleted.is_(False)).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        existing = _complete_assignments(user, _assignments(db, [user.id]).get(user.id, []))
        _validate_org_scope({a["org_id"] for a in existing} or {user.org_id}, policy, context)
        if any(role.is_platform_admin for role in user.roles) and not policy.is_platform_admin:
            raise HTTPException(status_code=403, detail="A tenant admin cannot delete a platform administrator")
        user.roles.clear()
        db.execute(delete(user_org_roles).where(user_org_roles.c.user_id == user.id))
        user.is_deleted = True
        user.deleted_by = current_user.id
        user.deleted_at = datetime.utcnow()
        db.commit()

    @CreadentialsInfo.put("/updateRole/{role_id}")
    async def update_role(
        self,
        role_id: int,
        payload: RoleBase,
        db: Session = Depends(get_db),
        policy: AccessPolicy = Depends(get_request_policy),
        context: OrgContext = Depends(get_org_context),
    ):
        _require(policy, "Edit_Role")
        role = db.query(Role).filter(Role.id == role_id, Role.is_deleted.is_(False)).first()
        if not role:
            raise HTTPException(status_code=404, detail="Role not found")
        if role.org_id is None and not policy.is_platform_admin:
            raise HTTPException(status_code=403, detail="System role templates require platform administration")
        if role.org_id is not None:
            _validate_org_scope({role.org_id}, policy, context)
        permissions = db.query(Permission).filter(Permission.id.in_(payload.permissions or [])).all()
        if not policy.is_platform_admin and any(p.name in PLATFORM_PERMISSION_NAMES for p in permissions):
            raise HTTPException(status_code=403, detail="Platform permissions cannot be granted by a tenant admin")
        role.name = payload.name
        role.permissions = permissions
        db.commit()
        db.refresh(role)
        return {"id": role.id, "name": role.name, "org_id": role.org_id, "permissions": [{"id": p.id, "name": p.name} for p in role.permissions]}

    @CreadentialsInfo.delete("/deleteRole/{role_id}")
    async def delete_role(
        self,
        role_id: int,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
        policy: AccessPolicy = Depends(get_request_policy),
        context: OrgContext = Depends(get_org_context),
    ):
        _require(policy, "Delete_Role")
        role = db.query(Role).filter(Role.id == role_id, Role.is_deleted.is_(False)).first()
        if not role:
            raise HTTPException(status_code=404, detail="Role not found")
        if role.org_id is None and not policy.is_platform_admin:
            raise HTTPException(status_code=403, detail="System role templates require platform administration")
        if role.org_id is not None:
            _validate_org_scope({role.org_id}, policy, context)
        db.execute(delete(user_org_roles).where(user_org_roles.c.role_id == role.id))
        role.users.clear()
        role.permissions.clear()
        role.is_deleted = True
        role.deleted_by = current_user.id
        role.deleted_at = datetime.utcnow()
        db.commit()

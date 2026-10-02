from fastapi_utils.cbv import cbv
from fastapi_utils.inferring_router import InferringRouter
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from Model.db import get_db
from Model import User, Role, Permission, Organisation
from Schema import UserBase, RoleBase
from Utils import *
from auth.dependencies import get_current_user
from fastapi import Depends, HTTPException
from auth.security import hash_password
from Services.user_org_role_sync import sync_user_org_roles
from Model.Credentials.user_org_roles import user_org_roles
from datetime import datetime

CreadentialsInfo = InferringRouter()

@cbv(CreadentialsInfo)
class CreadentialsInfoAPI:
    @CreadentialsInfo.get("/getRole")
    @CreadentialsInfo.get("/getRoles")
    async def getRole(self, db: Session = Depends(get_db)):
        roles = db.query(Role).options(joinedload(Role.permissions)).filter(Role.is_deleted == False).all()
        return [{"id": role.id, "name": role.name, "permissions": [p.id for p in role.permissions]} for role in roles]
    
    @CreadentialsInfo.get("/getUser")
    @CreadentialsInfo.get("/getUsers")
    async def getUsers(self, db: Session = Depends(get_db)):
        users = db.query(User).filter(User.is_deleted == False).options(joinedload(User.roles), joinedload(User.organisation)).all()
        all_orgs = {o.id: o.display_name or o.name for o in db.query(Organisation).all()}

        result = []
        for user in users:
            if user.allowed_org_ids and len(user.allowed_org_ids) > 0:
                selected_ids = user.allowed_org_ids
            elif user.org_id:
                selected_ids = [user.org_id]
            else:
                selected_ids = [1]

            if 1 in selected_ids:
                org_names = ["Root / All Tenant Access"]
            else:
                org_names = [all_orgs.get(oid, f"Org #{oid}") for oid in selected_ids]

            result.append({
                "id": user.id, 
                "username": user.username,
                "org_id": user.org_id or (selected_ids[0] if selected_ids else 1),
                "org_ids": selected_ids,
                "org_name": org_names[0] if org_names else "Unknown",
                "org_names": org_names,
                "roles": [role.name for role in user.roles]
            })
        return result
    
    @CreadentialsInfo.get("/getPermission")
    @CreadentialsInfo.get("/getRolePermissions")
    @CreadentialsInfo.get("/getPermissions")
    async def getPermissions(self, db: Session = Depends(get_db)):
        permissions = db.query(Permission).all()
        return [{"id": perm.id, "name": perm.name, "descriptionp" : perm.description} for perm in permissions]

    @CreadentialsInfo.get("/getOrganisations")
    async def getOrganisations(self, db: Session = Depends(get_db)):
        orgs = db.query(Organisation).filter(Organisation.is_active == True).all()
        return [{"id": o.id, "name": o.name, "display_name": o.display_name or o.name} for o in orgs]
    
    @CreadentialsInfo.post("/addPermission")
    async def addRole(self, payload: RoleBase, db: Session = Depends(get_db)):
        role_name = payload.name
        permissions_ids = payload.permissions or []
        
        if not role_name:
            raise HTTPException(status_code=422, detail="Role name is required")

        permission_objs = db.query(Permission).filter(Permission.id.in_(permissions_ids)).all()
        new_role = Role(name=role_name, permissions=permission_objs)

        db.add(new_role)
        db.commit()
        db.refresh(new_role)

        return {
            "id": new_role.id,
            "name": new_role.name,
            "permissions": [{"id": p.id, "name": p.name} for p in new_role.permissions]
        }
    
    @CreadentialsInfo.post("/addUser")
    async def addUser(self, payload: UserBase, db: Session = Depends(get_db)):
        username = payload.username or payload.name
        password = payload.password
        roles = payload.roles or []
        
        if payload.org_ids is not None and len(payload.org_ids) > 0:
            selected_org_ids = payload.org_ids
            primary_org_id = 1 if 1 in selected_org_ids else selected_org_ids[0]
        elif payload.org_id is not None:
            primary_org_id = payload.org_id
            selected_org_ids = [payload.org_id]
        else:
            primary_org_id = 1
            selected_org_ids = [1]
        
        if not username or not password:
            raise HTTPException(status_code=422, detail="Username and password are required")

        existing = db.query(User).filter(User.username == username, User.is_deleted == False).first()
        if existing:
            raise HTTPException(status_code=400, detail="Username already exists")

        new_user = User(
            username=username, 
            password_hash=hash_password(password), 
            org_id=primary_org_id,
            allowed_org_ids=selected_org_ids
        )
        
        int_ids = [r for r in roles if isinstance(r, int)]
        str_names = [r for r in roles if isinstance(r, str)]
        conditions = []
        if int_ids:
            conditions.append(Role.id.in_(int_ids))
        if str_names:
            conditions.append(Role.name.in_(str_names))
        if conditions:
            new_user.roles = db.query(Role).filter(Role.is_deleted == False).filter(or_(*conditions)).all()
        else:
            new_user.roles = []

        db.add(new_user)
        db.flush()
        sync_user_org_roles(db, new_user)
        db.commit()
        db.refresh(new_user)

        all_orgs = {o.id: o.display_name or o.name for o in db.query(Organisation).all()}
        returned_org_ids = new_user.allowed_org_ids if new_user.allowed_org_ids else [primary_org_id]
        if 1 in returned_org_ids:
            org_names = ["Root / All Tenant Access"]
        else:
            org_names = [all_orgs.get(oid, f"Org #{oid}") for oid in returned_org_ids]

        return {
            "id": new_user.id,
            "username": new_user.username,
            "org_id": primary_org_id,
            "org_ids": returned_org_ids,
            "org_name": org_names[0] if org_names else "Unknown",
            "org_names": org_names,
            "roles": [role.name for role in new_user.roles]
        }
    
    @CreadentialsInfo.delete("/deleteUser/{user_id}")
    async def delete_user(self, user_id: int, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
        user = db.query(User).filter(User.id == user_id, User.is_deleted == False).first()

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        user.roles.clear()
        db.execute(user_org_roles.delete().where(user_org_roles.c.user_id == user.id))
        user.is_deleted = True
        user.deleted_by = current_user.get("id") if isinstance(current_user, dict) else getattr(current_user, "id", None)
        user.deleted_at = datetime.utcnow()
        db.commit()
    
    @CreadentialsInfo.put("/updateUser/{user_id}")
    async def update_user(self, user_id: int, payload: UserBase, db: Session = Depends(get_db)):
        user = db.query(User).filter(User.id == user_id, User.is_deleted == False).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        username = payload.username or payload.name
        if username:
            user.username = username
        if payload.password:
            user.password_hash = hash_password(payload.password)
        
        if payload.org_ids is not None and len(payload.org_ids) > 0:
            selected_org_ids = payload.org_ids
            primary_org_id = 1 if 1 in selected_org_ids else selected_org_ids[0]
            user.org_id = primary_org_id
            user.allowed_org_ids = selected_org_ids
        elif payload.org_id is not None:
            user.org_id = payload.org_id
            user.allowed_org_ids = [payload.org_id]
            
        if payload.roles is not None:
            int_ids = [r for r in payload.roles if isinstance(r, int)]
            str_names = [r for r in payload.roles if isinstance(r, str)]
            conditions = []
            if int_ids:
                conditions.append(Role.id.in_(int_ids))
            if str_names:
                conditions.append(Role.name.in_(str_names))
            if conditions:
                user.roles = db.query(Role).filter(Role.is_deleted == False).filter(or_(*conditions)).all()
            else:
                user.roles = []
            
        db.flush()
        sync_user_org_roles(db, user)
        db.commit()
        db.refresh(user)

        all_orgs = {o.id: o.display_name or o.name for o in db.query(Organisation).all()}
        returned_org_ids = user.allowed_org_ids if user.allowed_org_ids else ([user.org_id] if user.org_id else [1])
        if 1 in returned_org_ids:
            org_names = ["Root / All Tenant Access"]
        else:
            org_names = [all_orgs.get(oid, f"Org #{oid}") for oid in returned_org_ids]

        return {
            "id": user.id, 
            "username": user.username,
            "org_id": user.org_id or (returned_org_ids[0] if returned_org_ids else 1),
            "org_ids": returned_org_ids,
            "org_name": org_names[0] if org_names else "Unknown",
            "org_names": org_names,
            "roles": [role.name for role in user.roles]
        }

    @CreadentialsInfo.put("/updateRole/{role_id}")
    async def update_role(self, role_id: int, payload: RoleBase, db: Session = Depends(get_db)):
        role = db.query(Role).filter(Role.id == role_id, Role.is_deleted == False).first()
        if not role:
            raise HTTPException(status_code=404, detail="Role not found")
            
        if payload.name:
            role.name = payload.name
            
        if payload.permissions is not None:
            permission_objs = db.query(Permission).filter(Permission.id.in_(payload.permissions)).all()
            role.permissions = permission_objs
            
        db.commit()
        db.refresh(role)
        return {"id": role.id, "name": role.name, "permissions": [{"id": p.id, "name": p.name} for p in role.permissions]}
    
    @CreadentialsInfo.delete("/deleteRole/{role_id}")
    async def deleteRole(self, role_id: int, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
        role = db.query(Role).filter(Role.id == role_id, Role.is_deleted == False).first()
        if not role:
            raise HTTPException(status_code=404, detail="Role not found")

        role.users.clear()
        role.permissions.clear()

        role.is_deleted = True
        role.deleted_by = current_user.get("id") if isinstance(current_user, dict) else getattr(current_user, "id", None)
        role.deleted_at = datetime.utcnow()
        db.commit()

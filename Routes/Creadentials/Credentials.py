from fastapi_utils.cbv import cbv
from fastapi_utils.inferring_router import InferringRouter
from fastapi import Depends
from sqlalchemy.orm import Session, joinedload

from Model.db import get_db
from Model import User, Role, Permission, Organisation
from Schema import UserBase, RoleBase
from Utils import *
from auth.dependencies import get_current_user
from fastapi import Depends, HTTPException
from auth.security import hash_password
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
            selected_ids = [user.org_id] if user.org_id else [1]
            if 1 in selected_ids:
                org_names = ["Root / All Tenant Access"]
            else:
                org_names = [all_orgs.get(oid, f"Org #{oid}") for oid in selected_ids]

            result.append({
                "id": user.id, 
                "username": user.username,
                "org_id": user.org_id or 1,
                "org_ids": selected_ids,
                "org_name": org_names[0],
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
        username = payload.username
        password = payload.password
        roles = payload.roles or []
        
        selected_org_ids = payload.org_ids or ([payload.org_id] if payload.org_id else [1])
        primary_org_id = 1 if 1 in selected_org_ids or not selected_org_ids else selected_org_ids[0]
        
        if not username or not password:
            raise HTTPException(status_code=422, detail="Username and password are required")

        new_user = User(username=username, password_hash=hash_password(password), org_id=primary_org_id)
        role_objs = db.query(Role).filter(Role.id.in_(roles)).all()
        new_user.roles = role_objs

        db.add(new_user)
        db.commit()
        db.refresh(new_user)

        all_orgs = {o.id: o.display_name or o.name for o in db.query(Organisation).all()}
        org_names = ["Root / All Tenant Access"] if primary_org_id == 1 else [all_orgs.get(oid, f"Org #{oid}") for oid in selected_org_ids]

        return {
            "id": new_user.id,
            "username": new_user.username,
            "org_id": primary_org_id,
            "org_ids": selected_org_ids,
            "org_name": org_names[0],
            "org_names": org_names,
            "roles": [role.name for role in role_objs]
        }
    
    @CreadentialsInfo.delete("/deleteUser/{user_id}")
    async def delete_user(self, user_id: int, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
        user = db.query(User).filter(User.id == user_id, User.is_deleted == False).first()

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        user.roles.clear()
        user.is_deleted = True
        user.deleted_by = current_user.get("id") if isinstance(current_user, dict) else getattr(current_user, "id", None)
        user.deleted_at = datetime.utcnow()
        db.commit()
    
    @CreadentialsInfo.put("/updateUser/{user_id}")
    async def update_user(self, user_id: int, payload: UserBase, db: Session = Depends(get_db)):
        user = db.query(User).filter(User.id == user_id, User.is_deleted == False).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        if payload.username:
            user.username = payload.username
        if payload.password:
            user.password_hash = hash_password(payload.password)
        
        selected_org_ids = payload.org_ids or ([payload.org_id] if payload.org_id is not None else [user.org_id or 1])
        primary_org_id = 1 if 1 in selected_org_ids or not selected_org_ids else selected_org_ids[0]
        user.org_id = primary_org_id
        
        if payload.roles is not None:
            role_objs = db.query(Role).filter(Role.id.in_(payload.roles)).all()
            user.roles = role_objs
            
        db.commit()
        db.refresh(user)

        all_orgs = {o.id: o.display_name or o.name for o in db.query(Organisation).all()}
        org_names = ["Root / All Tenant Access"] if primary_org_id == 1 else [all_orgs.get(oid, f"Org #{oid}") for oid in selected_org_ids]

        return {
            "id": user.id, 
            "username": user.username,
            "org_id": primary_org_id,
            "org_ids": selected_org_ids,
            "org_name": org_names[0],
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
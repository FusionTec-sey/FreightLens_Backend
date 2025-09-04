from fastapi_utils.cbv import cbv
from fastapi_utils.inferring_router import InferringRouter
from fastapi import Depends
from sqlalchemy.orm import Session, joinedload

from Model.db import get_db
from Model import User, Role, Permission
from Schema import UserBase, RoleBase
from Utils import *
# from ...auth.dependencies import get_current_user
from fastapi import  Depends, HTTPException
from auth.security import hash_password

CreadentialsInfo = InferringRouter()


@cbv(CreadentialsInfo)
class CreadentialsInfoAPI:
    @CreadentialsInfo.get("/getRole")
    async def getRole(self, db: Session = Depends(get_db)):
        roles = db.query(Role).all()
        return [{"id": role.id, "name": role.name} for role in roles]
    
    @CreadentialsInfo.get("/getUser")
    async def getUsers(self, db: Session = Depends(get_db)):
        users = db.query(User).options(joinedload(User.roles)).all()
        # roles = db.query(USer).filter().all()
        
        return [{"id": user.id, "username": user.username, "roles": [role.name for role in user.roles]} for user in users]
    
    @CreadentialsInfo.get("/getPermission")
    async def getPermissions(self, db: Session = Depends(get_db)):
        permissions = db.query(Permission).all()
        return [{"id": perm.id, "name": perm.name, "descriptionp" : perm.description} for perm in permissions]
    
    @CreadentialsInfo.post("/addPermission")
    async def addRole(self, payload: RoleBase, db: Session = Depends(get_db)):
        role_name = payload.name
        permissions_ids = payload.permissions or []
        
        print(role_name, permissions_ids)
        if not role_name:
            raise HTTPException(status_code=422, detail="Role name is required")

        # Fetch permission objects from DB
        permission_objs = db.query(Permission).filter(Permission.id.in_(permissions_ids)).all()

        # Create new role with permissions
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
        
        if not username or not password:
            raise HTTPException(status_code=422, detail="Username and password are required")
        # print(roles, username, password)
        # Create the new user
        new_user = User(username=username, password_hash=hash_password(password))

        # Fetch Role objects by IDs
        role_objs = db.query(Role).filter(Role.id.in_(roles)).all()

        # Assign roles
        new_user.roles = role_objs

        db.add(new_user)
        db.commit()
        db.refresh(new_user)

        return {
            "id": new_user.id,
            "username": new_user.username,
            "roles": [role.name for role in role_objs]
        }
    
    @CreadentialsInfo.delete("/deleteUser/{user_id}")
    async def delete_user(self, user_id: int, db: Session = Depends(get_db)):
        user = db.query(User).filter(User.id == user_id).first()

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Clear many-to-many relationships
        user.roles.clear()  # Removes all related role associations

        db.delete(user)     # Delete the user
        db.commit()
    
    @CreadentialsInfo.delete("/deleteRole/{role_id}")
    async def deleteRole(self, role_id: int, db: Session = Depends(get_db)):
        role = db.query(Role).filter(Role.id == role_id).first()
        if not role:
            raise HTTPException(status_code=404, detail="Role not found")

        # Clear many-to-many relationships
        role.users.clear()           # Unlink role from users (via user_roles)
        role.permissions.clear()     # Unlink role from permissions (via role_permissions)

        db.delete(role)
        db.commit()
    
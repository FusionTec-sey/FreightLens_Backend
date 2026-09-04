from fastapi import Depends, HTTPException, Header, status
from fastapi.security import OAuth2PasswordBearer
import jwt
from typing import Optional
from sqlalchemy.orm import Session

from Model.Credentials.users import User
from Model.Credentials.Organisation import Organisation
from Model.db import get_db
from auth.tokens import SECRET_KEY, ALGORITHM
from Utils.org_filter import OrgContext

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if not username:
            raise HTTPException(status_code=401, detail="Invalid token")

        user = db.query(User).filter(User.username == username).first()
        if not user:
            raise HTTPException(status_code=401, detail="User not found")

        db.refresh(user)
        user.is_root = (user.organisation.parent_org_id is None) if user.organisation else True
        user.modules = list(user.organisation.modules) if (user.organisation and user.organisation.modules) else ["LOGISTICS", "ORDERS"]
        user.plan = user.organisation.plan if (user.organisation and user.organisation.plan) else "complete"
        return user

    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

def get_org_context(
    user: User = Depends(get_current_user),
    x_active_org: Optional[str] = Header(None, alias="X-Active-Org"),
    db: Session = Depends(get_db)
) -> OrgContext:
    user_org_id = user.org_id or 1
    org = db.query(Organisation).filter_by(id=user_org_id).first()
    
    is_root = (org.parent_org_id is None) if org else True

    if is_root:
        all_orgs = db.query(Organisation.id).filter_by(is_active=True).all()
        allowed_ids = [o[0] for o in all_orgs]
        
        selected_id = None
        if x_active_org and x_active_org.isdigit():
            val = int(x_active_org)
            if val in allowed_ids:
                selected_id = val

        return OrgContext(
            current_org_id=user_org_id,
            allowed_org_ids=allowed_ids,
            is_root=True,
            selected_org_id=selected_id
        )
    else:
        return OrgContext(
            current_org_id=user_org_id,
            allowed_org_ids=[user_org_id],
            is_root=False,
            selected_org_id=user_org_id
        )

def require_roles(required_roles: list):
    def checker(user: User = Depends(get_current_user)):
        user_roles = [role.name for role in user.roles]
        if not any(role in user_roles for role in required_roles):
            raise HTTPException(status_code=403, detail="Insufficient role")
        return user
    return checker


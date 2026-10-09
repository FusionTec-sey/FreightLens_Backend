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
        user.is_root = bool(user.organisation and user.organisation.parent_org_id is None)
        user.modules = list(user.organisation.modules) if (user.organisation and user.organisation.modules) else []
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
    if user.org_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not assigned to an organisation",
        )

    user_org_id = user.org_id
    org = db.query(Organisation).filter_by(id=user_org_id).first()
    if not org or not org.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User organisation is inactive or unavailable",
        )

    is_root_platform_admin = org.parent_org_id is None and any(
        bool(getattr(role, "is_platform_admin", False)) for role in user.roles
    )
    if is_root_platform_admin:
        candidate_ids = [row[0] for row in db.query(Organisation.id).filter(
            Organisation.is_active.is_(True)
        ).all()]
    else:
        configured_ids = user.allowed_org_ids
        candidate_ids = [user_org_id] if configured_ids is None else configured_ids
        candidate_ids = list(dict.fromkeys(
            org_id for org_id in candidate_ids if isinstance(org_id, int) and org_id > 0
        ))
    active_orgs = (
        db.query(Organisation.id)
        .filter(Organisation.id.in_(candidate_ids), Organisation.is_active.is_(True))
        .all()
        if candidate_ids
        else []
    )
    allowed_ids = [row[0] for row in active_orgs]
    if not allowed_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User has no active organisation assignments",
        )

    selected_id = None
    if x_active_org is not None:
        if not x_active_org.isdigit():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="X-Active-Org must be a numeric organisation id",
            )
        selected_id = int(x_active_org)
        if selected_id not in allowed_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Selected organisation is not assigned to this user",
            )
    elif len(allowed_ids) == 1:
        selected_id = allowed_ids[0]

    return OrgContext(
        current_org_id=user_org_id,
        allowed_org_ids=allowed_ids,
        is_root=org.parent_org_id is None,
        selected_org_id=selected_id,
    )

def require_roles(required_roles: list):
    def checker(user: User = Depends(get_current_user)):
        user_roles = [role.name for role in user.roles]
        if not any(role in user_roles for role in required_roles):
            raise HTTPException(status_code=403, detail="Insufficient role")
        return user
    return checker


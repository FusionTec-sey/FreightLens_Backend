from fastapi import APIRouter, Depends, HTTPException, status, Body
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import timedelta
import jwt

from Model.Credentials.users import User
from Model.Credentials.roles import Role
from Model.Credentials.permissions import Permission
from Model.db import get_db

from auth.security import verify_password
from auth.tokens import create_access_token, create_refresh_token
from auth.dependencies import get_current_user

router = APIRouter()

ACCESS_TOKEN_EXPIRE_HOUR = 1
REFRESH_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7
fake_refresh_tokens = {}

@router.post("/token")
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    access_token = create_access_token({"sub": user.username, "roles": "admin"}, timedelta(hours=ACCESS_TOKEN_EXPIRE_HOUR))
    refresh_token = create_refresh_token({"sub": user.username}, timedelta(minutes=REFRESH_TOKEN_EXPIRE_MINUTES))

    fake_refresh_tokens[user.username] = refresh_token

    permissions = (
        db.query(Permission.name)
        .join(Role.permissions)
        .join(Role.users)
        .filter(User.username == form_data.username)
        .distinct()
        .all()
    )

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "permissions": [p[0] for p in permissions],
    }

@router.post("/refresh")
async def refresh_token(refresh_token: str = Body(...), db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(refresh_token, "super-secret", algorithms=["HS256"])
        username = payload.get("sub")
        if not username:
            raise HTTPException(status_code=401, detail="Invalid token")

        if fake_refresh_tokens.get(username) != refresh_token:
            raise HTTPException(status_code=401, detail="Refresh token mismatch")

        access_token = create_access_token({"sub": username}, timedelta(hours=ACCESS_TOKEN_EXPIRE_HOUR))
        return {"access_token": access_token, "token_type": "bearer"}

    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Refresh token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

@router.get("/users/me")
async def get_me(current_user: User = Depends(get_current_user)):
    return {
        "username": current_user.username,
        "roles": [r.name for r in current_user.roles]
    }

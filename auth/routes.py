import hashlib
import logging
from datetime import datetime, timedelta

import jwt
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from Model.Credentials.users import User
from Model.Credentials.roles import Role
from Model.Credentials.permissions import Permission
from Model.Credentials.refresh_tokens import RefreshToken
from Model.db import get_db

from auth.security import verify_password
from auth.tokens import create_access_token, create_refresh_token, SECRET_KEY, ALGORITHM
from auth.dependencies import get_current_user

logger = logging.getLogger("auth")

router = APIRouter()

ACCESS_TOKEN_EXPIRE_HOUR = 1
REFRESH_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days


def _hash_token(raw_token: str) -> str:
    """Return SHA-256 hex digest of a raw refresh token string."""
    return hashlib.sha256(raw_token.encode()).hexdigest()


from limiter import limiter

@router.post("/token")
@limiter.limit("5/minute")
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        logger.warning(
            "Failed login attempt | username=%s | ip=%s",
            form_data.username,
            request.client.host if request.client else "unknown",
        )
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # ── Build token with actual DB roles (not hardcoded "admin") ──────────────
    user_roles = [role.name for role in user.roles]
    access_token = create_access_token(
        {"sub": user.username, "roles": user_roles},
        timedelta(hours=ACCESS_TOKEN_EXPIRE_HOUR),
    )
    refresh_token = create_refresh_token(
        {"sub": user.username},
        timedelta(minutes=REFRESH_TOKEN_EXPIRE_MINUTES),
    )

    # ── Persist hashed refresh token in DB (replaces in-memory dict) ──────────
    db_token = RefreshToken(
        user_id=user.id,
        token_hash=_hash_token(refresh_token),
        expires_at=datetime.utcnow() + timedelta(minutes=REFRESH_TOKEN_EXPIRE_MINUTES),
    )
    db.add(db_token)
    db.commit()

    # ── Fetch user permissions for response ───────────────────────────────────
    permissions = (
        db.query(Permission.name)
        .join(Role.permissions)
        .join(Role.users)
        .filter(User.username == form_data.username)
        .distinct()
        .all()
    )

    logger.info("Successful login | username=%s", user.username)
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "permissions": [p[0] for p in permissions],
    }


@router.post("/refresh")
async def refresh_token_endpoint(
    refresh_token: str = Body(...),
    db: Session = Depends(get_db),
):
    try:
        payload = jwt.decode(refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if not username:
            raise HTTPException(status_code=401, detail="Invalid token")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Refresh token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

    # ── Validate against DB record ─────────────────────────────────────────────
    token_hash = _hash_token(refresh_token)
    db_token = (
        db.query(RefreshToken)
        .filter_by(token_hash=token_hash, revoked=0)
        .first()
    )
    if not db_token or db_token.expires_at < datetime.utcnow():
        logger.warning("Invalid or expired refresh token attempt | username=%s", username)
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    # ── Issue new access token ─────────────────────────────────────────────────
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    user_roles = [role.name for role in user.roles]
    access_token = create_access_token(
        {"sub": username, "roles": user_roles},
        timedelta(hours=ACCESS_TOKEN_EXPIRE_HOUR),
    )
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/logout")
async def logout(
    refresh_token: str = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Revoke the provided refresh token so it can no longer be used."""
    token_hash = _hash_token(refresh_token)
    db_token = db.query(RefreshToken).filter_by(token_hash=token_hash, revoked=0).first()
    if db_token:
        db_token.revoked = 1
        db.commit()
    logger.info("User logged out | username=%s", current_user.username)
    return {"message": "Logged out successfully"}


@router.get("/users/me")
async def get_me(current_user: User = Depends(get_current_user)):
    return {
        "username": current_user.username,
        "roles": [r.name for r in current_user.roles],
    }

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from auth.dependencies import get_current_user, get_org_context
from auth.policy import AccessPolicy, get_request_policy
from Model.Credentials.users import User
from Model.db import get_db
from Utils.org_filter import OrgContext

def require_module(module_name: str):
    """
    FastAPI dependency factory.
    Returns HTTP 403 if tenant has not subscribed to module_name.
    Does NOT block root/superadmin users.

    Usage:
        @router.get("/containers", dependencies=[Depends(require_module("LOGISTICS"))])
    """
    async def _check(
        current_user: User = Depends(get_current_user),
        org_context: OrgContext = Depends(get_org_context),
        db: Session = Depends(get_db),
        policy: AccessPolicy = Depends(get_request_policy),
    ):
        if policy.is_platform_admin:
            return True
        if module_name not in policy.module_names:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Every selected organisation must have access to the '{module_name}' module."
            )
        return True
    return _check

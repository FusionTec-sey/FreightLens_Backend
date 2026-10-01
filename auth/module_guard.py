from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from auth.dependencies import get_current_user, get_org_context
from auth.security_guards import is_platform_admin_user
from Model.Credentials.Organisation import Organisation
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
    ):
        if is_platform_admin_user(current_user):
            return True

        scope_ids = (
            [org_context.selected_org_id]
            if org_context.selected_org_id is not None
            else org_context.allowed_org_ids
        )
        organisations = (
            db.query(Organisation)
            .filter(Organisation.id.in_(scope_ids), Organisation.is_active.is_(True))
            .all()
        )
        if len(organisations) != len(scope_ids):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="One or more selected organisations are inactive or unavailable.",
            )
        if any(module_name not in list(organisation.modules or []) for organisation in organisations):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Every selected organisation must have access to the '{module_name}' module."
            )
        return True
    return _check

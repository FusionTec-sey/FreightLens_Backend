from fastapi import Depends, HTTPException, status
from auth.dependencies import get_current_user
from Model.Credentials.users import User

def require_module(module_name: str):
    """
    FastAPI dependency factory.
    Returns HTTP 403 if tenant has not subscribed to module_name.
    Does NOT block root/superadmin users.

    Usage:
        @router.get("/containers", dependencies=[Depends(require_module("LOGISTICS"))])
    """
    async def _check(current_user: User = Depends(get_current_user)):
        if getattr(current_user, "is_root", False):
            return True
        modules = getattr(current_user, "modules", None) or ["LOGISTICS", "ORDERS"]
        if module_name not in modules:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Your organisation does not have access to the '{module_name}' module. Please upgrade your subscription."
            )
        return True
    return _check

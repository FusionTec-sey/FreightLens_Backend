"""
Centralized Server-Side Security & Role-Based Access Control (RBAC) Module
Enforces zero-trust authorization, field-level data redaction, and action restrictions.
"""

from typing import List, Optional, Union
from fastapi import Depends, HTTPException, status
from Model.Credentials.users import User
from Utils.org_filter import OrgContext
from auth.dependencies import get_current_user, get_org_context

# Explicit permissions that grant financial visibility / mutation
FINANCIAL_PERMISSIONS = {
    "Manage_Financials",
    "View_Financials",
    "Add_Payment",
    "Edit_Payment",
    "Delete_Payment",
    "Approve_Variance",
    "View_VendorQuote",
    "Compare_Quote",
}

# Sourcing permissions that must be kept confidential from floor requestors
SOURCING_PERMISSIONS = {
    "Send_RFQ",
    "View_VendorQuote",
    "Add_VendorQuote",
    "Compare_Quote",
    "Approve_Quote",
    "Issue_PO",
}

ADMIN_ROLE_NAMES = {"admin", "administrator", "root", "super_admin", "superadmin"}
PLATFORM_ADMIN_ROLE_NAMES = {"root", "super_admin", "superadmin"}


def is_admin_user(user: User) -> bool:
    if not user:
        return False
    return any(
        getattr(role, "name", "").strip().lower() in ADMIN_ROLE_NAMES
        for role in getattr(user, "roles", [])
    )


def is_platform_admin_user(user: User) -> bool:
    """Return true only for an explicitly named platform-wide administrator."""
    if not user:
        return False
    return any(
        getattr(role, "name", "").strip().lower() in PLATFORM_ADMIN_ROLE_NAMES
        for role in getattr(user, "roles", [])
    )


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Require an administrator role without granting cross-tenant access."""
    if not is_admin_user(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access is required",
        )
    return current_user


def require_root_admin(
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context),
) -> User:
    """Restrict platform administration to administrators in the root tenant."""
    if not org_context.is_root or not is_platform_admin_user(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Root administrator access is required",
        )
    return current_user

def has_permission(user: User, permission_name: str) -> bool:
    """
    Checks whether a user holds a specific permission through an assigned role.
    Only an explicit platform administrator bypasses permission checks.
    """
    if not user:
        return False

    if is_platform_admin_user(user):
        return True

    user_roles = getattr(user, "roles", [])
    for r in user_roles:
        for p in getattr(r, "permissions", []):
            p_name = getattr(p, "name", "")
            if p_name == permission_name:
                return True
            # Implicit viewing permission: If user has Edit/Add/Delete for a resource, they can View it
            if permission_name.startswith("View_"):
                suffix = permission_name[5:]
                if p_name in [f"Edit_{suffix}", f"Add_{suffix}", f"Delete_{suffix}", suffix]:
                    return True
    return False

def can_access_sourcing(user: User, specific_permission: Optional[str] = None) -> bool:
    """
    Checks whether a user has authority to perform or view commercial sourcing.
    Access requires an explicit sourcing permission, except for platform administrators.
    """
    if not user:
        return False

    if is_platform_admin_user(user):
        return True

    if specific_permission:
        return has_permission(user, specific_permission)
    return any(has_permission(user, permission) for permission in SOURCING_PERMISSIONS)

def is_financial_user(user: User, org_context: Optional[OrgContext] = None) -> bool:
    """
    Authoritative server-side check for whether a user is authorized to view
    confidential financial data (unit prices, total amounts, vendor quotes, payment ledger).
    Tenant hierarchy and ordinary administrative roles do not grant financial clearance.
    """
    if not user:
        return False

    if is_platform_admin_user(user):
        return True

    for r in getattr(user, "roles", []):
        for p in getattr(r, "permissions", []):
            p_name = getattr(p, "name", "")
            if p_name in FINANCIAL_PERMISSIONS:
                return True

    return False

def can_view_supplier_user(user: User, org_context: Optional[OrgContext] = None) -> bool:
    """
    Authoritative server-side check for whether a user is authorized to view
    confidential vendor/supplier identities, contacts, and quotes.
    Allowed for platform administrators or explicit supplier permissions.
    Forbidden for: Tenant admins without explicit supplier permissions, floor staff, warehouse, requestors.
    """
    if not user:
        return False

    if is_platform_admin_user(user):
        return True

    for r in getattr(user, "roles", []):
        for p in getattr(r, "permissions", []):
            p_name = getattr(p, "name", "")
            if p_name in ["View_Supplier", "Supplier", "Edit_Supplier", "Add_Supplier"]:
                return True

    return False

def can_view_bl_user(user: User, org_context: Optional[OrgContext] = None) -> bool:
    """
    Authoritative server-side check for whether a user is authorized to view
    Bills of Lading records and details.
    Allowed for:
    - Root tenant super admins ('super_admin', 'root')
    - Explicit permissions: View_BL, Add_BillOfLanding, Edit_BillOfLanding, Delete_BillOfLanding, BillOfLanding
    Forbidden if access has been withdrawn.
    """
    if not user:
        return False

    user_roles = [getattr(r, "name", "").lower() for r in getattr(user, "roles", []) if hasattr(r, "name")]
    if any(r in ["super_admin", "root", "superadmin"] for r in user_roles):
        return True

    for r in getattr(user, "roles", []):
        for p in getattr(r, "permissions", []):
            p_name = getattr(p, "name", "")
            if p_name in ["View_BL", "Add_BillOfLanding", "Edit_BillOfLanding", "Delete_BillOfLanding", "BillOfLanding"]:
                return True

    return False

def require_permission(permission_name: str):
    """
    FastAPI dependency that enforces a required permission, raising 403 Forbidden if absent.
    """
    def dependency(
        current_user: User = Depends(get_current_user),
        org_context: OrgContext = Depends(get_org_context)
    ):
        if not has_permission(current_user, permission_name):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Operation forbidden: Missing required permission '{permission_name}'."
            )
        return current_user
    return dependency

def require_sourcing_permission(permission_name: str):
    """
    FastAPI dependency that enforces a required sourcing permission (or admin/procurement authority),
    raising 403 Forbidden for requestors and unauthorized staff.
    """
    def dependency(
        current_user: User = Depends(get_current_user),
        org_context: OrgContext = Depends(get_org_context)
    ) -> User:
        if not can_access_sourcing(current_user, permission_name):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access forbidden: Sourcing activity '{permission_name}' is confidential and restricted."
            )
        return current_user
    return dependency

def require_financial_access(
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context)
) -> User:
    """
    FastAPI dependency that enforces financial/procurement visibility,
    raising 403 Forbidden for non-financial staff.
    """
    if not is_financial_user(current_user, org_context):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: Financial and confidential purchasing data requires authorization."
        )
    return current_user

def can_view_documents_user(user: User, org_context: Optional[OrgContext] = None) -> bool:
    """Check if user has clearance to view container and operational documents/proofs."""
    if not user:
        return False
    user_roles = [getattr(r, "name", "").lower() for r in getattr(user, "roles", []) if hasattr(r, "name")]
    if any(r in ["super_admin", "root", "superadmin"] for r in user_roles):
        return True
    for r in getattr(user, "roles", []):
        for p in getattr(r, "permissions", []):
            p_name = getattr(p, "name", "")
            if p_name in ["View_Document", "Upload_Document", "Edit_Document", "Delete_Document", "View_OrderDocument", "Document"]:
                return True
    return False

def can_upload_documents_user(user: User, org_context: Optional[OrgContext] = None) -> bool:
    """Check if user has clearance to upload container attachments, shipping documents, or photos."""
    if not user:
        return False
    user_roles = [getattr(r, "name", "").lower() for r in getattr(user, "roles", []) if hasattr(r, "name")]
    if any(r in ["super_admin", "root", "superadmin"] for r in user_roles):
        return True
    for r in getattr(user, "roles", []):
        for p in getattr(r, "permissions", []):
            p_name = getattr(p, "name", "")
            if p_name in ["Upload_Document", "Edit_Document", "Add_Document", "Edit_Container"]:
                return True
    return False

def can_delete_documents_user(user: User, org_context: Optional[OrgContext] = None) -> bool:
    """Check if user has clearance to delete documents/proofs."""
    if not user:
        return False
    user_roles = [getattr(r, "name", "").lower() for r in getattr(user, "roles", []) if hasattr(r, "name")]
    if any(r in ["super_admin", "root", "superadmin"] for r in user_roles):
        return True
    for r in getattr(user, "roles", []):
        for p in getattr(r, "permissions", []):
            p_name = getattr(p, "name", "")
            if p_name in ["Delete_Document", "Delete_Container"]:
                return True
    return False

def can_view_orders_user(user: User, org_context: Optional[OrgContext] = None) -> bool:
    """Check if user has clearance to view linked purchase orders."""
    if not user:
        return False
    user_roles = [getattr(r, "name", "").lower() for r in getattr(user, "roles", []) if hasattr(r, "name")]
    if any(r in ["super_admin", "root", "superadmin"] for r in user_roles):
        return True
    for r in getattr(user, "roles", []):
        for p in getattr(r, "permissions", []):
            p_name = getattr(p, "name", "")
            if p_name in ["View_Order", "Order", "Add_Order", "Edit_Order"]:
                return True
    return False

def can_view_receipts_user(user: User, org_context: Optional[OrgContext] = None) -> bool:
    """Check if user has clearance to view goods receiving operations."""
    if not user:
        return False
    user_roles = [getattr(r, "name", "").lower() for r in getattr(user, "roles", []) if hasattr(r, "name")]
    if any(r in ["super_admin", "root", "superadmin"] for r in user_roles):
        return True
    for r in getattr(user, "roles", []):
        for p in getattr(r, "permissions", []):
            p_name = getattr(p, "name", "")
            if p_name in ["View_GoodsReceipt", "Verify_Receipt", "Edit_Receipt", "Submit_Receipt"]:
                return True
    return False

def can_view_defects_user(user: User, org_context: Optional[OrgContext] = None) -> bool:
    """Check if user has clearance to view container and receiving defect reports."""
    if not user:
        return False
    user_roles = [getattr(r, "name", "").lower() for r in getattr(user, "roles", []) if hasattr(r, "name")]
    if any(r in ["super_admin", "root", "superadmin"] for r in user_roles):
        return True
    for r in getattr(user, "roles", []):
        for p in getattr(r, "permissions", []):
            p_name = getattr(p, "name", "")
            if p_name in ["View_Defect", "Defect", "Add_Defect", "Edit_Defect", "Resolve_Defect"]:
                return True
    return False


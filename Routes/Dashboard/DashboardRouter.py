import logging
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import or_

from Model.db import get_db
from Model.Credentials.users import User
from Model.Credentials.roles import Role
from Model.containermgmt.Dashboard.DashboardTemplate import DashboardTemplate
from auth.dependencies import get_current_user, get_org_context
from reporting.policy import AccessPolicy, get_access_policy
from Utils.org_filter import OrgContext
from Services.dashboard_registry import (
    get_authorized_widgets,
    get_user_layout,
    save_user_layout,
    reset_user_layout,
    calculate_dashboard_data,
    ROLE_DEFAULT_TEMPLATES,
    WIDGET_MAP
)

logger = logging.getLogger("containerMgmt.dashboard")

DashboardRouter = APIRouter(prefix="/dashboard", tags=["Dashboard Planner & Widget Registry"])


# ── Pydantic Request Schemas ──────────────────────────────────────────────────

class WidgetLayoutItemSchema(BaseModel):
    id: str
    col_span: Optional[int] = 1
    visible: Optional[bool] = True


class SaveDashboardLayoutSchema(BaseModel):
    layout_mode: Optional[str] = "grid"
    template_id: Optional[int] = None
    widgets: List[WidgetLayoutItemSchema]


class SaveDashboardTemplateSchema(BaseModel):
    name: str
    role_name: str
    role_id: Optional[int] = None
    description: Optional[str] = None
    is_default: Optional[bool] = False
    widgets: List[WidgetLayoutItemSchema]


class UpdateDashboardTemplateSchema(BaseModel):
    name: Optional[str] = None
    role_name: Optional[str] = None
    role_id: Optional[int] = None
    description: Optional[str] = None
    is_default: Optional[bool] = None
    widgets: Optional[List[WidgetLayoutItemSchema]] = None


# ── Dashboard API Endpoints ───────────────────────────────────────────────────

def _resolve_dashboard_role(db: Session, org_id: int, role_id=None, role_name=None) -> Role:
    query = db.query(Role).filter(
        Role.is_deleted.is_(False),
        or_(Role.org_id.is_(None), Role.org_id == org_id),
    )
    if role_id is not None:
        role = query.filter(Role.id == role_id).first()
    else:
        role = query.filter(Role.name == role_name).order_by(Role.org_id.desc().nullslast()).first()
    if role is None:
        raise HTTPException(status_code=422, detail="Dashboard role was not found for this organisation")
    return role

@DashboardRouter.get("/widgets", summary="List all available widgets for authenticated user")
def list_available_widgets(
    current_user: User = Depends(get_current_user),
    access_policy: AccessPolicy = Depends(get_access_policy),
):
    """
    Returns the list of all dashboard widgets available to the user based on
    their role and granted module permissions.
    """
    widgets = get_authorized_widgets(access_policy.scoped_user)
    return {"widgets": widgets, "total": len(widgets)}


@DashboardRouter.get("/layout", summary="Fetch active dashboard layout")
def get_active_dashboard_layout(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context),
    access_policy: AccessPolicy = Depends(get_access_policy),
):
    """
    Returns user's custom layout, or falls back to role default template,
    ensuring all returned widgets are verified against user permissions.
    """
    layout = get_user_layout(db, access_policy.scoped_user, org_context)
    return layout


@DashboardRouter.post("/layout", summary="Save user customized dashboard layout")
def save_dashboard_layout(
    payload: SaveDashboardLayoutSchema,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context),
    access_policy: AccessPolicy = Depends(get_access_policy),
):
    """
    Saves user-specific dashboard arrangement and widget choices.
    Requires Customize_Dashboard permission.
    """
    if not access_policy.has("Customize_Dashboard"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to customize the dashboard."
        )

    res = save_user_layout(
        db=db,
        current_user=access_policy.scoped_user,
        org_context=org_context,
        widgets=[w.dict() for w in payload.widgets],
        layout_mode=payload.layout_mode or "grid",
        template_id=payload.template_id
    )
    return {"message": "Dashboard layout saved successfully", "result": res}


@DashboardRouter.post("/reset", summary="Reset layout to role default")
def reset_dashboard_layout(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context),
    access_policy: AccessPolicy = Depends(get_access_policy),
):
    """
    Resets the user's dashboard layout to their role's default template.
    """
    layout = reset_user_layout(db, access_policy.scoped_user, org_context)
    return {"message": "Dashboard layout reset to role default", "layout": layout}


@DashboardRouter.get("/data", summary="Fetch live KPI metrics and datasets for active widgets")
def get_dashboard_metrics(
    year: Optional[int] = Query(None, description="Year for monthly trend aggregations"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context),
    access_policy: AccessPolicy = Depends(get_access_policy),
):
    """
    Fetches real-time KPI data, counts, and chart datasets for all widgets
    the user has access to, with multi-tenant row isolation applied.
    """
    principal = access_policy.scoped_user
    layout = get_user_layout(db, principal, org_context)
    widget_ids = [item["id"] for item in layout.get("widgets", []) if item.get("visible", True)]
    data = calculate_dashboard_data(
        db, principal, org_context, year=year, widget_ids=widget_ids
    )
    return {"data": data}


@DashboardRouter.get("/templates", summary="List role dashboard templates")
def list_dashboard_templates(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context),
):
    """
    Lists system default role templates and custom templates created for the organization.
    """
    templates = []
    # 1. Preset templates
    for role, tpl in ROLE_DEFAULT_TEMPLATES.items():
        templates.append({
            "id": f"preset_{role.lower()}",
            "is_preset": True,
            "role_name": role,
            "name": tpl["name"],
            "description": tpl["description"],
            "widgets": tpl["widgets"]
        })

    # 2. Database custom templates
    rows = db.query(DashboardTemplate).filter(
        DashboardTemplate.org_id == org_context.org_id,
        DashboardTemplate.is_deleted.is_(False),
    ).order_by(DashboardTemplate.name).all()
    for row in rows:
            templates.append({
                "id": row.id,
                "is_preset": False,
                "name": row.name,
                "role_id": row.role_id,
                "role_name": row.role.name if row.role else None,
                "description": row.description,
                "is_default": row.is_default,
                "widgets": row.widgets,
            })

    return {"templates": templates}


@DashboardRouter.post("/templates", summary="Create role dashboard template")
def create_dashboard_template(
    payload: SaveDashboardTemplateSchema,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context),
    access_policy: AccessPolicy = Depends(get_access_policy),
):
    """
    Creates a new dashboard template for a role.
    Requires Manage_DashboardTemplate permission.
    """
    if not access_policy.has("Manage_DashboardTemplate"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to manage dashboard templates."
        )

    requested_widgets = [w.model_dump() for w in payload.widgets]
    authorized_ids = {
        widget["id"] for widget in get_authorized_widgets(access_policy.scoped_user)
    }
    forbidden = sorted({item["id"] for item in requested_widgets} - authorized_ids)
    if forbidden:
        raise HTTPException(status_code=403, detail=f"Unauthorized dashboard widgets: {', '.join(forbidden)}")

    role = _resolve_dashboard_role(
        db, org_context.org_id, payload.role_id, payload.role_name
    )

    # If setting as default, clear other defaults for this role
    if payload.is_default:
        db.query(DashboardTemplate).filter(
            DashboardTemplate.org_id == org_context.org_id,
            DashboardTemplate.role_id == role.id,
            DashboardTemplate.is_deleted.is_(False),
        ).update({"is_default": False}, synchronize_session=False)

    template = DashboardTemplate(
        org_id=org_context.org_id,
        name=payload.name.strip(),
        role_id=role.id,
        description=payload.description.strip() if payload.description else None,
        is_default=bool(payload.is_default),
        widgets=requested_widgets,
        created_by=current_user.id,
        updated_by=current_user.id,
    )
    db.add(template)
    db.commit()
    db.refresh(template)

    return {"message": f"Dashboard template '{payload.name}' created successfully.", "id": template.id}


@DashboardRouter.put("/templates/{template_id}", summary="Update existing dashboard template")
def update_dashboard_template(
    template_id: int,
    payload: UpdateDashboardTemplateSchema,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context),
    access_policy: AccessPolicy = Depends(get_access_policy),
):
    """
    Updates an existing custom dashboard template.
    Requires Manage_DashboardTemplate permission.
    """
    if not access_policy.has("Manage_DashboardTemplate"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to manage dashboard templates."
        )

    template = db.query(DashboardTemplate).filter(
        DashboardTemplate.id == template_id,
        DashboardTemplate.org_id == org_context.org_id,
        DashboardTemplate.is_deleted.is_(False),
    ).first()
    if template is None:
        raise HTTPException(status_code=404, detail="Dashboard template not found.")

    role = template.role
    if payload.role_id is not None or payload.role_name is not None:
        role = _resolve_dashboard_role(
            db, org_context.org_id, payload.role_id, payload.role_name
        )

    # If setting as default, clear other defaults for this role
    if payload.is_default is True:
        db.query(DashboardTemplate).filter(
            DashboardTemplate.org_id == org_context.org_id,
            DashboardTemplate.role_id == role.id,
            DashboardTemplate.id != template.id,
            DashboardTemplate.is_deleted.is_(False),
        ).update({"is_default": False}, synchronize_session=False)

    if payload.name is not None:
        template.name = payload.name.strip()
    if role is not None:
        template.role_id = role.id
    if payload.description is not None:
        template.description = payload.description.strip()
    if payload.is_default is not None:
        template.is_default = payload.is_default
    if payload.widgets is not None:
        requested_widgets = [w.model_dump() for w in payload.widgets]
        authorized_ids = {
            widget["id"] for widget in get_authorized_widgets(access_policy.scoped_user)
        }
        forbidden = sorted({item["id"] for item in requested_widgets} - authorized_ids)
        if forbidden:
            raise HTTPException(status_code=403, detail=f"Unauthorized dashboard widgets: {', '.join(forbidden)}")
        template.widgets = requested_widgets
    template.updated_by = current_user.id
    db.commit()

    return {"message": "Dashboard template updated successfully."}


@DashboardRouter.delete("/templates/{template_id}", summary="Delete dashboard template")
def delete_dashboard_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context),
    access_policy: AccessPolicy = Depends(get_access_policy),
):
    """
    Soft-deletes a custom dashboard template.
    Requires Manage_DashboardTemplate permission.
    """
    if not access_policy.has("Manage_DashboardTemplate"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to delete dashboard templates."
        )

    template = db.query(DashboardTemplate).filter(
        DashboardTemplate.id == template_id,
        DashboardTemplate.org_id == org_context.org_id,
        DashboardTemplate.is_deleted.is_(False),
    ).first()
    if template is None:
        raise HTTPException(status_code=404, detail="Dashboard template not found.")

    from datetime import datetime, timezone
    template.is_deleted = True
    template.deleted_at = datetime.now(timezone.utc)
    template.deleted_by = current_user.id
    db.commit()

    return {"message": "Dashboard template deleted successfully."}


@DashboardRouter.post("/templates/{template_id}/set-default", summary="Set template as default for its role")
def set_template_as_default(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context),
    access_policy: AccessPolicy = Depends(get_access_policy),
):
    """
    Designates a template as the primary default for its target role.
    """
    if not access_policy.has("Manage_DashboardTemplate"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to manage dashboard templates."
        )

    template = db.query(DashboardTemplate).filter(
        DashboardTemplate.id == template_id,
        DashboardTemplate.org_id == org_context.org_id,
        DashboardTemplate.is_deleted.is_(False),
    ).first()
    if template is None:
        raise HTTPException(status_code=404, detail="Dashboard template not found.")

    db.query(DashboardTemplate).filter(
        DashboardTemplate.org_id == org_context.org_id,
        DashboardTemplate.role_id == template.role_id,
        DashboardTemplate.is_deleted.is_(False),
    ).update({"is_default": False}, synchronize_session=False)
    template.is_default = True
    template.updated_by = current_user.id
    db.commit()

    role_name = template.role.name if template.role else str(template.role_id)
    return {"message": f"Template assigned as default for role '{role_name}'."}

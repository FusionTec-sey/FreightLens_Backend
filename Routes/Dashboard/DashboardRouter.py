import logging
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from Model.db import get_db
from Model.Credentials.users import User
from auth.dependencies import get_current_user, get_org_context
from auth.security_guards import has_permission, require_permission
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
    description: Optional[str] = None
    is_default: Optional[bool] = False
    widgets: List[WidgetLayoutItemSchema]


class UpdateDashboardTemplateSchema(BaseModel):
    name: Optional[str] = None
    role_name: Optional[str] = None
    description: Optional[str] = None
    is_default: Optional[bool] = None
    widgets: Optional[List[WidgetLayoutItemSchema]] = None


# ── Dashboard API Endpoints ───────────────────────────────────────────────────

@DashboardRouter.get("/widgets", summary="List all available widgets for authenticated user")
async def list_available_widgets(
    current_user: User = Depends(get_current_user),
):
    """
    Returns the list of all dashboard widgets available to the user based on
    their role and granted module permissions.
    """
    widgets = get_authorized_widgets(current_user)
    return {"widgets": widgets, "total": len(widgets)}


@DashboardRouter.get("/layout", summary="Fetch active dashboard layout")
async def get_active_dashboard_layout(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context),
):
    """
    Returns user's custom layout, or falls back to role default template,
    ensuring all returned widgets are verified against user permissions.
    """
    layout = get_user_layout(db, current_user, org_context)
    return layout


@DashboardRouter.post("/layout", summary="Save user customized dashboard layout")
async def save_dashboard_layout(
    payload: SaveDashboardLayoutSchema,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context),
):
    """
    Saves user-specific dashboard arrangement and widget choices.
    Requires Customize_Dashboard permission.
    """
    if not has_permission(current_user, "Customize_Dashboard"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to customize the dashboard."
        )

    res = save_user_layout(
        db=db,
        current_user=current_user,
        org_context=org_context,
        widgets=[w.dict() for w in payload.widgets],
        layout_mode=payload.layout_mode or "grid",
        template_id=payload.template_id
    )
    return {"message": "Dashboard layout saved successfully", "result": res}


@DashboardRouter.post("/reset", summary="Reset layout to role default")
async def reset_dashboard_layout(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context),
):
    """
    Resets the user's dashboard layout to their role's default template.
    """
    layout = reset_user_layout(db, current_user, org_context)
    return {"message": "Dashboard layout reset to role default", "layout": layout}


@DashboardRouter.get("/data", summary="Fetch live KPI metrics and datasets for active widgets")
async def get_dashboard_metrics(
    year: Optional[int] = Query(None, description="Year for monthly trend aggregations"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context),
):
    """
    Fetches real-time KPI data, counts, and chart datasets for all widgets
    the user has access to, with multi-tenant row isolation applied.
    """
    data = calculate_dashboard_data(db, current_user, org_context, year=year)
    return {"data": data}


@DashboardRouter.get("/templates", summary="List role dashboard templates")
async def list_dashboard_templates(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context),
):
    """
    Lists system default role templates and custom templates created for the organization.
    """
    is_postgres = (db.bind.dialect.name == "postgresql")
    biz_schema = "containermgmt." if is_postgres else ""

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
    try:
        rows = db.execute(text(f"""
            SELECT id, name, role_name, description, is_default, widgets
            FROM {biz_schema}dashboard_templates
            WHERE org_id = :org_id AND is_deleted = FALSE
            ORDER BY name ASC
        """), {"org_id": org_context.org_id}).fetchall()

        for r in rows:
            templates.append({
                "id": r[0],
                "is_preset": False,
                "name": r[1],
                "role_name": r[2],
                "description": r[3],
                "is_default": r[4],
                "widgets": r[5]
            })
    except Exception as e:
        logger.error(f"Failed to fetch db dashboard templates: {e}")

    return {"templates": templates}


@DashboardRouter.post("/templates", summary="Create role dashboard template")
async def create_dashboard_template(
    payload: SaveDashboardTemplateSchema,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context),
):
    """
    Creates a new dashboard template for a role.
    Requires Manage_DashboardTemplate permission.
    """
    if not has_permission(current_user, "Manage_DashboardTemplate"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to manage dashboard templates."
        )

    import json
    from datetime import datetime, timezone
    is_postgres = (db.bind.dialect.name == "postgresql")
    biz_schema = "containermgmt." if is_postgres else ""
    now = datetime.now(timezone.utc)

    # If setting as default, clear other defaults for this role
    if payload.is_default:
        db.execute(text(f"""
            UPDATE {biz_schema}dashboard_templates
            SET is_default = FALSE
            WHERE org_id = :org_id AND role_name = :role_name
        """), {"org_id": org_context.org_id, "role_name": payload.role_name})

    widgets_json = json.dumps([w.dict() for w in payload.widgets])

    res = db.execute(text(f"""
        INSERT INTO {biz_schema}dashboard_templates
        (org_id, name, role_name, description, is_default, widgets, created_by, updated_by, created_at, updated_at)
        VALUES (:org_id, :name, :role_name, :description, :is_default, CAST(:widgets AS jsonb), :user_id, :user_id, :now, :now)
        RETURNING id
    """), {
        "org_id": org_context.org_id,
        "name": payload.name.strip(),
        "role_name": payload.role_name,
        "description": payload.description.strip() if payload.description else None,
        "is_default": payload.is_default or False,
        "widgets": widgets_json,
        "user_id": current_user.id,
        "now": now
    })
    new_id = res.scalar()
    db.commit()

    return {"message": f"Dashboard template '{payload.name}' created successfully.", "id": new_id}


@DashboardRouter.put("/templates/{template_id}", summary="Update existing dashboard template")
async def update_dashboard_template(
    template_id: int,
    payload: UpdateDashboardTemplateSchema,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context),
):
    """
    Updates an existing custom dashboard template.
    Requires Manage_DashboardTemplate permission.
    """
    if not has_permission(current_user, "Manage_DashboardTemplate"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to manage dashboard templates."
        )

    import json
    from datetime import datetime, timezone
    is_postgres = (db.bind.dialect.name == "postgresql")
    biz_schema = "containermgmt." if is_postgres else ""
    now = datetime.now(timezone.utc)

    # Verify template exists and belongs to org
    existing = db.execute(text(f"""
        SELECT id, role_name, is_default FROM {biz_schema}dashboard_templates
        WHERE id = :id AND org_id = :org_id AND is_deleted = FALSE
    """), {"id": template_id, "org_id": org_context.org_id}).fetchone()

    if not existing:
        raise HTTPException(status_code=404, detail="Dashboard template not found.")

    target_role = payload.role_name if payload.role_name is not None else existing[1]

    # If setting as default, clear other defaults for this role
    if payload.is_default is True:
        db.execute(text(f"""
            UPDATE {biz_schema}dashboard_templates
            SET is_default = FALSE
            WHERE org_id = :org_id AND role_name = :role_name AND id != :id
        """), {"org_id": org_context.org_id, "role_name": target_role, "id": template_id})

    updates = []
    params = {"id": template_id, "org_id": org_context.org_id, "user_id": current_user.id, "now": now}

    if payload.name is not None:
        updates.append("name = :name")
        params["name"] = payload.name.strip()
    if payload.role_name is not None:
        updates.append("role_name = :role_name")
        params["role_name"] = payload.role_name
    if payload.description is not None:
        updates.append("description = :description")
        params["description"] = payload.description.strip()
    if payload.is_default is not None:
        updates.append("is_default = :is_default")
        params["is_default"] = payload.is_default
    if payload.widgets is not None:
        updates.append("widgets = CAST(:widgets AS jsonb)")
        params["widgets"] = json.dumps([w.dict() for w in payload.widgets])

    updates.append("updated_by = :user_id")
    updates.append("updated_at = :now")

    sql = f"""
        UPDATE {biz_schema}dashboard_templates
        SET {', '.join(updates)}
        WHERE id = :id AND org_id = :org_id
    """
    db.execute(text(sql), params)
    db.commit()

    return {"message": "Dashboard template updated successfully."}


@DashboardRouter.delete("/templates/{template_id}", summary="Delete dashboard template")
async def delete_dashboard_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context),
):
    """
    Soft-deletes a custom dashboard template.
    Requires Manage_DashboardTemplate permission.
    """
    if not has_permission(current_user, "Manage_DashboardTemplate"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to delete dashboard templates."
        )

    from datetime import datetime, timezone
    is_postgres = (db.bind.dialect.name == "postgresql")
    biz_schema = "containermgmt." if is_postgres else ""
    now = datetime.now(timezone.utc)

    existing = db.execute(text(f"""
        SELECT id FROM {biz_schema}dashboard_templates
        WHERE id = :id AND org_id = :org_id AND is_deleted = FALSE
    """), {"id": template_id, "org_id": org_context.org_id}).fetchone()

    if not existing:
        raise HTTPException(status_code=404, detail="Dashboard template not found.")

    db.execute(text(f"""
        UPDATE {biz_schema}dashboard_templates
        SET is_deleted = TRUE, deleted_at = :now, deleted_by = :user_id
        WHERE id = :id AND org_id = :org_id
    """), {"id": template_id, "org_id": org_context.org_id, "user_id": current_user.id, "now": now})
    db.commit()

    return {"message": "Dashboard template deleted successfully."}


@DashboardRouter.post("/templates/{template_id}/set-default", summary="Set template as default for its role")
async def set_template_as_default(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context),
):
    """
    Designates a template as the primary default for its target role.
    """
    if not has_permission(current_user, "Manage_DashboardTemplate"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to manage dashboard templates."
        )

    from datetime import datetime, timezone
    is_postgres = (db.bind.dialect.name == "postgresql")
    biz_schema = "containermgmt." if is_postgres else ""
    now = datetime.now(timezone.utc)

    existing = db.execute(text(f"""
        SELECT id, role_name FROM {biz_schema}dashboard_templates
        WHERE id = :id AND org_id = :org_id AND is_deleted = FALSE
    """), {"id": template_id, "org_id": org_context.org_id}).fetchone()

    if not existing:
        raise HTTPException(status_code=404, detail="Dashboard template not found.")

    role_name = existing[1]

    # Reset existing defaults for this role
    db.execute(text(f"""
        UPDATE {biz_schema}dashboard_templates
        SET is_default = FALSE
        WHERE org_id = :org_id AND role_name = :role_name
    """), {"org_id": org_context.org_id, "role_name": role_name})

    # Set new default
    db.execute(text(f"""
        UPDATE {biz_schema}dashboard_templates
        SET is_default = TRUE, updated_by = :user_id, updated_at = :now
        WHERE id = :id AND org_id = :org_id
    """), {"id": template_id, "org_id": org_context.org_id, "user_id": current_user.id, "now": now})
    db.commit()

    return {"message": f"Template assigned as default for role '{role_name}'."}


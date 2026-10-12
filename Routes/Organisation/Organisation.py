import logging

from fastapi import Depends, HTTPException, Body, APIRouter, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import date, datetime

from Model.db import get_db
from auth.security_guards import has_permission
from Model.containermgmt.Report.OrgPrintProfile import OrgPrintProfile
from sqlalchemy import func
from Model.Credentials import Organisation, User, Role
from Model.containermgmt import ContainerDetails, BillOfLanding
from auth.dependencies import get_current_user, get_org_context
from auth.security_guards import require_admin, require_root_admin
from Utils.org_filter import OrgContext
from Services.navigation_service import seed_default_menu
from Services.document_number_service import (
    DOC_TYPES,
    RESET_POLICIES,
    format_number,
    peek_document_number,
)
from Model.containermgmt.MasterData.DocumentNumberSeries import DocumentNumberSeries

logger = logging.getLogger("containerMgmt.organisation")

OrganisationRouter = APIRouter(prefix="/organisations", tags=["Organisation Management"])

class OrganisationSchema(BaseModel):
    id: int
    name: str
    display_name: Optional[str] = None
    parent_org_id: Optional[int] = None
    is_active: bool
    logo_url: Optional[str] = None
    modules: Optional[List[str]] = ["LOGISTICS", "ORDERS"]
    plan: Optional[str] = "complete"
    user_count: Optional[int] = 0
    container_count: Optional[int] = 0
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class OrganisationCreateSchema(BaseModel):
    name: str
    display_name: str
    parent_org_id: Optional[int] = 1
    logo_url: Optional[str] = None
    modules: Optional[List[str]] = ["LOGISTICS", "ORDERS"]
    plan: Optional[str] = "complete"

class OrganisationUpdateSchema(BaseModel):
    display_name: Optional[str] = None
    is_active: Optional[bool] = None
    logo_url: Optional[str] = None
    modules: Optional[List[str]] = None
    plan: Optional[str] = None

@OrganisationRouter.get("/configuration")
async def list_organisation_configuration(
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user),
):
    """One row per company, saying which parts of its setup are done.

    Company settings were spread across four screens, so a half-configured
    company looked exactly like a finished one until a document printed wrong.
    This backs a single list that answers "is this company ready?" without
    opening anything.

    Scoped to the companies the caller may already see, and read-only: every
    setting is still edited through the screen that owns it, with that screen's
    own permission.
    """
    if not (has_permission(current_user, "View_Setting")
            or has_permission(current_user, "Edit_Setting")
            or org_context.is_root):
        raise HTTPException(status_code=403, detail="Access forbidden: Missing View_Setting permission")

    orgs = (
        db.query(Organisation)
        .filter(Organisation.id.in_(org_context.allowed_org_ids))
        .order_by(Organisation.id.asc())
        .all()
    )

    # Counted once for every company rather than per row.
    series_counts = dict(
        db.query(DocumentNumberSeries.org_id, func.count(DocumentNumberSeries.id))
        .filter(
            DocumentNumberSeries.is_deleted == False,  # noqa: E712
            DocumentNumberSeries.is_active == True,  # noqa: E712
        )
        .group_by(DocumentNumberSeries.org_id)
        .all()
    )
    profile_orgs = {
        row[0] for row in db.query(OrgPrintProfile.org_id)
        .filter(OrgPrintProfile.is_deleted == False).all()  # noqa: E712
    }
    user_counts = dict(
        db.query(User.org_id, func.count(User.id)).group_by(User.org_id).all()
    )

    return [
        {
            "id": org.id,
            "name": org.name,
            "display_name": org.display_name or org.name,
            "code": getattr(org, "code", None),
            "parent_org_id": org.parent_org_id,
            "is_active": org.is_active,
            "is_root": org.parent_org_id is None,
            "modules": org.modules or [],
            "user_count": user_counts.get(org.id, 0),
            # What is configured, so the list can say what is missing.
            "numbering_active": series_counts.get(org.id, 0),
            "has_print_profile": org.id in profile_orgs,
        }
        for org in orgs
    ]


@OrganisationRouter.get("", response_model=List[OrganisationSchema])
async def list_organisations(
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
):
    orgs = (
        db.query(Organisation)
        .filter(
            Organisation.id.in_(org_context.allowed_org_ids),
            Organisation.is_active.is_(True),
        )
        .all()
    )
    results = []
    for org in orgs:
        u_count = db.query(User).filter_by(org_id=org.id).count()
        c_count = db.query(ContainerDetails).filter_by(org_id=org.id).count()
        schema = OrganisationSchema.model_validate(org)
        schema.user_count = u_count
        schema.container_count = c_count
        results.append(schema)
    return results

@OrganisationRouter.get("/tree")
async def get_organisation_tree(
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
):
    root_orgs = (
        db.query(Organisation)
        .filter(
            Organisation.parent_org_id.is_(None),
            Organisation.id.in_(org_context.allowed_org_ids),
            Organisation.is_active.is_(True),
        )
        .all()
    )
    res = []
    for root in root_orgs:
        children = (
            db.query(Organisation)
            .filter(
                Organisation.parent_org_id == root.id,
                Organisation.id.in_(org_context.allowed_org_ids),
                Organisation.is_active.is_(True),
            )
            .all()
        )
        res.append({
            "id": root.id,
            "name": root.name,
            "display_name": root.display_name,
            "is_active": root.is_active,
            "children": [
                {
                    "id": c.id,
                    "name": c.name,
                    "display_name": c.display_name,
                    "is_active": c.is_active,
                }
                for c in children
            ]
        })
    return res

@OrganisationRouter.post("", response_model=OrganisationSchema)
async def create_organisation(
    data: OrganisationCreateSchema = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    root_admin: User = Depends(require_root_admin),
    org_context: OrgContext = Depends(get_org_context),
):
    if not org_context.is_root:
        raise HTTPException(status_code=403, detail="Only Root Organisation administrators can create sub-organisations.")
    
    existing = db.query(Organisation).filter_by(name=data.name.strip().lower()).first()
    if existing:
        raise HTTPException(status_code=400, detail="An organisation with this slug name already exists.")

    new_org = Organisation(
        name=data.name.strip().lower(),
        display_name=data.display_name.strip(),
        parent_org_id=data.parent_org_id or 1,
        logo_url=data.logo_url,
        modules=data.modules or ["LOGISTICS", "ORDERS"],
        plan=data.plan or "complete",
        is_active=True
    )
    db.add(new_org)
    db.commit()
    db.refresh(new_org)

    # Give the new tenant a navigation menu it can edit straight away. Failing
    # here must not fail the organisation: /navigation/my-menu falls back to the
    # registry-derived default when an organisation has no rows.
    try:
        seed_default_menu(db, new_org.id, user_id=current_user.id, commit=True)
    except Exception:
        db.rollback()
        logger.exception("Could not seed the default menu for org_id=%s", new_org.id)

    schema = OrganisationSchema.model_validate(new_org)
    schema.user_count = 0
    schema.container_count = 0
    return schema

@OrganisationRouter.patch("/{org_id}", response_model=OrganisationSchema)
async def update_organisation(
    org_id: int,
    data: OrganisationUpdateSchema = Body(...),
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(require_admin),
):
    if org_id not in org_context.allowed_org_ids:
        raise HTTPException(status_code=403, detail="Access denied.")

    org = db.query(Organisation).filter_by(id=org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found.")

    if data.display_name is not None:
        org.display_name = data.display_name.strip()
    if data.is_active is not None and org_context.is_root:
        org.is_active = data.is_active
    if data.logo_url is not None:
        org.logo_url = data.logo_url
    if data.modules is not None and org_context.is_root:
        org.modules = data.modules
    if data.plan is not None and org_context.is_root:
        org.plan = data.plan

    db.commit()
    db.refresh(org)

    u_count = db.query(User).filter_by(org_id=org.id).count()
    c_count = db.query(ContainerDetails).filter_by(org_id=org.id).count()
    schema = OrganisationSchema.model_validate(org)
    schema.user_count = u_count
    schema.container_count = c_count
    return schema


# ── Admin Console Overview Stats ──────────────────────────────────────────────
AdminRouter = APIRouter(prefix="/admin", tags=["Admin Console"])

@AdminRouter.get("/stats")
async def get_admin_stats(
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
):
    if not org_context.is_root:
        raise HTTPException(status_code=403, detail="Admin Console is restricted to Root Organisation administrators.")

    total_orgs = db.query(Organisation).count()
    total_users = db.query(User).count()
    total_containers = db.query(ContainerDetails).count()
    total_bols = db.query(BillOfLanding).count()

    org_breakdown = []
    orgs = db.query(Organisation).all()
    for o in orgs:
        org_breakdown.append({
            "id": o.id,
            "name": o.name,
            "display_name": o.display_name,
            "parent_id": o.parent_org_id,
            "is_active": o.is_active,
            "modules": o.modules or ["LOGISTICS", "ORDERS", "INVENTORY"],
            "plan": o.plan or "complete",
            "users": db.query(User).filter_by(org_id=o.id).count(),
            "containers": db.query(ContainerDetails).filter_by(org_id=o.id).count(),
            "bols": db.query(BillOfLanding).filter_by(org_id=o.id).count(),
        })

    return {
        "summary": {
            "total_organisations": total_orgs,
            "total_users": total_users,
            "total_containers": total_containers,
            "total_bols": total_bols,
        },
        "organisations": org_breakdown
    }

@AdminRouter.patch("/organisations/{org_id}/modules")
async def update_org_modules(
    org_id: int,
    modules: List[str] = Body(..., embed=True),
    plan: Optional[str] = Body(None, embed=True),
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
):
    if not org_context.is_root:
        raise HTTPException(status_code=403, detail="Admin Console is restricted to Root Organisation administrators.")
    
    valid_modules = {"LOGISTICS", "ORDERS", "INVENTORY"}
    if not set(modules).issubset(valid_modules):
        raise HTTPException(status_code=400, detail=f"Invalid modules specified. Allowed: {list(valid_modules)}")
    
    org = db.query(Organisation).filter_by(id=org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")
        
    org.modules = modules
    if plan:
        org.plan = plan
    db.commit()
    db.refresh(org)
    return {
        "success": True,
        "org_id": org.id,
        "name": org.display_name or org.name,
        "modules": org.modules,
        "plan": org.plan
    }

@AdminRouter.get("/settings")
async def get_admin_settings(
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
):
    orgs = db.query(Organisation).order_by(Organisation.id.asc()).all()

    # Numbering used to be reported here as f"REQ-{code}", computed per request
    # and stored nowhere, so the screen showed a value it could not save. These
    # now come from the configured series.
    series_rows = (
        db.query(DocumentNumberSeries)
        .filter(DocumentNumberSeries.is_deleted == False)  # noqa: E712
        .all()
    )
    by_org = {}
    for row in series_rows:
        by_org.setdefault(row.org_id, []).append({
            "id": row.id,
            "doc_type": row.doc_type,
            "doc_label": DOC_TYPES.get(row.doc_type, row.doc_type),
            "prefix": row.prefix or "",
            "suffix": row.suffix or "",
            "padding": row.padding,
            "next_number": row.next_number,
            "reset_policy": row.reset_policy,
            "date_token": row.date_token,
            "is_active": row.is_active,
            # Produced by the same code that issues the number, so the preview
            # cannot drift from what a document will actually get.
            "preview": format_number(row, row.next_number),
        })

    companies = []
    for o in orgs:
        code = getattr(o, "code", None) or f"ORG{o.id}"
        rows = sorted(by_org.get(o.id, []), key=lambda r: r["doc_type"])
        companies.append({
            "id": o.id,
            "code": code,
            "name": o.display_name or o.name,
            "active": o.is_active,
            "number_series": rows,
        })

    return {
        "groups": [{"id": 1, "name": "Sahaj Group of Companies"}],
        "companies": companies,
    }

@AdminRouter.patch("/companies/{company_id}")
async def update_company_settings(
    company_id: int,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
):
    if not org_context.is_root:
        raise HTTPException(status_code=403, detail="Only Root administrators can update company settings.")

    org = db.query(Organisation).filter_by(id=company_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")

    if "name" in payload and payload["name"]:
        new_name = payload["name"].strip()
        org.display_name = new_name
        # Keep Consignee in sync
        from Model.containermgmt.Cinfo.Consignee import Consignee
        consignee = db.query(Consignee).filter_by(org_id=company_id).first()
        if consignee:
            consignee.consignee_name = new_name

    if "active" in payload and payload["active"] is not None:
        org.is_active = bool(payload["active"])

    db.commit()
    db.refresh(org)

    code = getattr(org, "code", None) or f"ORG{org.id}"
    return {
        "id": org.id,
        "code": code,
        "name": org.display_name or org.name,
        "active": org.is_active,
    }

@AdminRouter.patch("/number-series/{series_id}")
async def update_number_series(
    series_id: int,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
    current_user: User = Depends(get_current_user),
):
    """Save one company's numbering for one document type.

    Lowering next_number below what has already been issued is allowed but
    reported back as a warning: it is occasionally right after a false start,
    and usually a mistake whose collision would otherwise only surface later,
    as a failed save by whoever creates the next document.
    """
    if not org_context.is_root:
        raise HTTPException(status_code=403, detail="Only Root administrators can change numbering.")

    series = (
        db.query(DocumentNumberSeries)
        .filter(
            DocumentNumberSeries.id == series_id,
            DocumentNumberSeries.is_deleted == False,  # noqa: E712
        )
        .first()
    )
    if not series:
        raise HTTPException(status_code=404, detail="Number series not found")

    if "prefix" in payload:
        series.prefix = (payload.get("prefix") or "").strip()[:30]
    if "suffix" in payload:
        series.suffix = (payload.get("suffix") or "").strip()[:30]

    if "padding" in payload and payload["padding"] is not None:
        try:
            padding = int(payload["padding"])
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Padding must be a whole number.")
        if not 0 <= padding <= 12:
            raise HTTPException(status_code=400, detail="Padding must be between 0 and 12.")
        series.padding = padding

    if "reset_policy" in payload and payload["reset_policy"]:
        policy = str(payload["reset_policy"]).lower()
        if policy not in RESET_POLICIES:
            raise HTTPException(
                status_code=400,
                detail=f"Reset must be one of: {', '.join(RESET_POLICIES)}.",
            )
        series.reset_policy = policy

    if "date_token" in payload:
        token = (payload.get("date_token") or "").strip()[:20]
        if token:
            # Reject a token now rather than at document-creation time.
            try:
                date.today().strftime(token)
            except (ValueError, TypeError):
                raise HTTPException(status_code=400, detail="That date format cannot be used.")
        series.date_token = token or None

    warning = None
    if "next_number" in payload and payload["next_number"] is not None:
        try:
            requested = int(payload["next_number"])
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Start number must be a whole number.")
        if requested < 1:
            raise HTTPException(status_code=400, detail="Start number must be 1 or higher.")
        if requested < series.next_number:
            warning = (
                f"{requested} is below the current counter ({series.next_number}). "
                "Numbers already issued may be repeated."
            )
        series.next_number = requested

    if "is_active" in payload and payload["is_active"] is not None:
        series.is_active = bool(payload["is_active"])

    series.updated_by = current_user.id
    db.commit()
    db.refresh(series)

    return {
        "id": series.id,
        "org_id": series.org_id,
        "doc_type": series.doc_type,
        "doc_label": DOC_TYPES.get(series.doc_type, series.doc_type),
        "prefix": series.prefix or "",
        "suffix": series.suffix or "",
        "padding": series.padding,
        "next_number": series.next_number,
        "reset_policy": series.reset_policy,
        "date_token": series.date_token,
        "is_active": series.is_active,
        "preview": format_number(series, series.next_number),
        "warning": warning,
    }


@AdminRouter.patch("/groups/{group_id}")
async def update_company_group(
    group_id: int,
    payload: dict = Body(...),
    org_context: OrgContext = Depends(get_org_context),
):
    if not org_context.is_root:
        raise HTTPException(status_code=403, detail="Only Root administrators can update group settings.")
    return {
        "id": group_id,
        "name": payload.get("name", "Sahaj Group of Companies"),
    }

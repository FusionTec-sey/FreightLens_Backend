from fastapi import Depends, HTTPException, Body, APIRouter, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime

from Model.db import get_db
from Model.Credentials import Organisation, User, Role
from Model.containermgmt import ContainerDetails, BillOfLanding
from auth.dependencies import get_current_user, get_org_context, require_roles
from Utils.org_filter import OrgContext

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

@OrganisationRouter.get("", response_model=List[OrganisationSchema])
async def list_organisations(
    db: Session = Depends(get_db),
    org_context: OrgContext = Depends(get_org_context),
):
    query = db.query(Organisation)
    if not org_context.is_root:
        query = query.filter(Organisation.id.in_(org_context.allowed_org_ids))
    
    orgs = query.all()
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
    root_orgs = db.query(Organisation).filter_by(parent_org_id=None).all()
    res = []
    for root in root_orgs:
        children = db.query(Organisation).filter_by(parent_org_id=root.id).all()
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
):
    if not org_context.is_root and org_id != org_context.current_org_id:
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
    companies = []
    for o in orgs:
        code = getattr(o, "code", None) or f"ORG{o.id}"
        companies.append({
            "id": o.id,
            "code": code,
            "name": o.display_name or o.name,
            "request_prefix": f"REQ-{code}",
            "po_prefix": f"PO-{code}",
            "active": o.is_active,
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
        "request_prefix": payload.get("request_prefix", f"REQ-{code}"),
        "po_prefix": payload.get("po_prefix", f"PO-{code}"),
        "active": org.is_active,
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

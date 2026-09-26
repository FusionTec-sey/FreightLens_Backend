"""
Services/report_template_service.py
Service layer for managing Report Templates and their Version histories.
Enforces multi-tenant boundaries and read-only protection on system templates.
"""
import logging
from typing import Optional, List, Tuple, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, func
from fastapi import HTTPException

from Model.containermgmt.Report.ReportTemplate import ReportTemplate
from Model.containermgmt.Report.ReportTemplateVersion import ReportTemplateVersion
from Model.Credentials.users import User
from Utils.org_filter import OrgContext
from Schema.ReportSchema import (
    ReportTemplateCreate,
    ReportTemplateUpdate,
    ReportTemplateClone,
    ReportTemplateVersionCreate,
)
from Services.report_template_validator import validate_template

logger = logging.getLogger("containerMgmt.report_template_service")


def list_templates(
    db: Session,
    org_context: OrgContext,
    category: Optional[str] = None,
    is_active: Optional[bool] = None,
    search: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
) -> Tuple[List[ReportTemplate], int]:
    """Lists templates accessible to the organization (System templates + Org-owned templates)."""
    # Tenant boundary: system templates (is_system=True) OR owned by one of the user's allowed orgs
    org_condition = or_(
        ReportTemplate.is_system == True,
        ReportTemplate.org_id.in_(org_context.allowed_org_ids),
    )

    query = db.query(ReportTemplate).filter(
        ReportTemplate.is_deleted == False,
        org_condition,
    )

    if category:
        query = query.filter(ReportTemplate.category == category.upper())

    if is_active is not None:
        query = query.filter(ReportTemplate.is_active == is_active)

    if search and search.strip():
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                ReportTemplate.name.ilike(term),
                ReportTemplate.slug.ilike(term),
                ReportTemplate.description.ilike(term),
            )
        )

    total = query.count()
    items = query.order_by(ReportTemplate.is_system.desc(), ReportTemplate.name.asc()).offset(skip).limit(limit).all()
    return items, total


def get_template(db: Session, template_id: int, org_context: OrgContext) -> ReportTemplate:
    """Retrieves a single template ensuring organization boundary clearance."""
    template = db.query(ReportTemplate).filter(
        ReportTemplate.id == template_id,
        ReportTemplate.is_deleted == False,
    ).first()

    if not template:
        raise HTTPException(status_code=404, detail="Report template not found.")

    if not template.is_system and template.org_id not in org_context.allowed_org_ids:
        raise HTTPException(status_code=403, detail="Access denied to this report template.")

    return template


def get_active_version_data(db: Session, template: ReportTemplate) -> Optional[ReportTemplateVersion]:
    """Gets the active version record for a template."""
    if template.active_version_id:
        v = db.query(ReportTemplateVersion).filter(
            ReportTemplateVersion.id == template.active_version_id,
            ReportTemplateVersion.is_deleted == False,
        ).first()
        if v:
            return v
    if template.active_version:
        return db.query(ReportTemplateVersion).filter(
            ReportTemplateVersion.template_id == template.id,
            ReportTemplateVersion.version_number == template.active_version,
            ReportTemplateVersion.is_deleted == False,
        ).first()
    return None


def create_custom_template(
    db: Session,
    data: ReportTemplateCreate,
    user: User,
    org_context: OrgContext,
) -> ReportTemplate:
    """Creates a new customer-defined report template under the user's organization."""
    # Check slug collision within the organization
    existing = db.query(ReportTemplate).filter(
        ReportTemplate.slug == data.slug,
        ReportTemplate.org_id == org_context.current_org_id,
        ReportTemplate.is_deleted == False,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"A template with slug '{data.slug}' already exists in your organization.")

    # Validate initial version content if provided
    initial_ver = data.initial_version
    if initial_ver:
        is_valid, errors, _ = validate_template(
            html_content=initial_ver.html_content,
            css_content=initial_ver.css_content,
            header_html=initial_ver.header_html,
            footer_html=initial_ver.footer_html,
            resolver_key=data.resolver_key,
        )
        if not is_valid:
            raise HTTPException(status_code=422, detail={"message": "Template validation failed", "errors": errors})

    template = ReportTemplate(
        slug=data.slug,
        name=data.name,
        description=data.description,
        category=data.category.upper(),
        resolver_key=data.resolver_key,
        entity_type=data.entity_type,
        is_system=False,
        is_active=data.is_active if data.is_active is not None else True,
        page_size=data.page_size or "A4",
        orientation=data.orientation or "portrait",
        org_id=org_context.current_org_id,
        created_by=user.id,
    )
    db.add(template)
    db.flush()

    if initial_ver:
        ver = ReportTemplateVersion(
            template_id=template.id,
            version_number=1,
            html_content=initial_ver.html_content,
            css_content=initial_ver.css_content,
            header_html=initial_ver.header_html,
            footer_html=initial_ver.footer_html,
            status="PUBLISHED",
            change_notes=initial_ver.changelog or "Initial template version",
            created_by=user.id,
        )
        db.add(ver)
        db.flush()
        template.active_version_id = ver.id

    db.commit()
    db.refresh(template)
    return template


def clone_template(
    db: Session,
    source_template_id: int,
    clone_data: ReportTemplateClone,
    user: User,
    org_context: OrgContext,
) -> ReportTemplate:
    """Clones an existing (typically system) template into a tenant-owned custom template."""
    source = get_template(db, source_template_id, org_context)
    source_ver = get_active_version_data(db, source)

    if not source_ver:
        raise HTTPException(status_code=400, detail="Source template has no active version to clone.")

    target_name = clone_data.name or f"{source.name} (Custom)"
    target_slug = clone_data.slug or f"{source.slug}_custom_{org_context.current_org_id}"

    # Ensure unique slug
    existing = db.query(ReportTemplate).filter(
        ReportTemplate.slug == target_slug,
        ReportTemplate.org_id == org_context.current_org_id,
        ReportTemplate.is_deleted == False,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"A template with slug '{target_slug}' already exists in your organization.")

    new_template = ReportTemplate(
        slug=target_slug,
        name=target_name,
        description=clone_data.description or source.description,
        category=source.category,
        resolver_key=source.resolver_key,
        entity_type=source.entity_type,
        is_system=False,
        is_active=True,
        page_size=source.page_size,
        orientation=source.orientation,
        org_id=org_context.current_org_id,
        created_by=user.id,
    )
    db.add(new_template)
    db.flush()

    new_version = ReportTemplateVersion(
        template_id=new_template.id,
        version_number=1,
        html_content=source_ver.html_content,
        css_content=source_ver.css_content,
        header_html=source_ver.header_html,
        footer_html=source_ver.footer_html,
        status="PUBLISHED",
        change_notes=f"Cloned from '{source.name}' v{source_ver.version_number}",
        created_by=user.id,
    )
    db.add(new_version)
    db.flush()
    new_template.active_version_id = new_version.id

    db.commit()
    db.refresh(new_template)
    return new_template


def update_template_metadata(
    db: Session,
    template_id: int,
    data: ReportTemplateUpdate,
    user: User,
    org_context: OrgContext,
) -> ReportTemplate:
    """Updates metadata on a tenant-owned template. System templates cannot be modified."""
    template = get_template(db, template_id, org_context)

    if template.is_system:
        raise HTTPException(status_code=400, detail="System templates are read-only. Clone this template to make customizations.")

    for field, val in data.model_dump(exclude_unset=True).items():
        if hasattr(template, field):
            setattr(template, field, val)

    template.updated_by = user.id
    db.commit()
    db.refresh(template)
    return template


def delete_template(db: Session, template_id: int, user: User, org_context: OrgContext):
    """Soft-deletes a tenant-owned template. System templates cannot be deleted."""
    template = get_template(db, template_id, org_context)

    if template.is_system:
        raise HTTPException(status_code=400, detail="System templates cannot be deleted.")

    template.is_deleted = True
    template.deleted_by = user.id
    db.commit()


def create_template_version(
    db: Session,
    template_id: int,
    data: ReportTemplateVersionCreate,
    user: User,
    org_context: OrgContext,
) -> ReportTemplateVersion:
    """Creates a new draft version for a tenant-owned template."""
    template = get_template(db, template_id, org_context)

    if template.is_system:
        raise HTTPException(status_code=400, detail="System templates cannot be modified. Clone this template to create custom versions.")

    is_valid, errors, _ = validate_template(
        html_content=data.html_content,
        css_content=data.css_content,
        header_html=data.header_html,
        footer_html=data.footer_html,
        resolver_key=template.resolver_key,
    )
    if not is_valid:
        raise HTTPException(status_code=422, detail={"message": "Template validation failed", "errors": errors})

    # Find highest current version
    max_ver = db.query(func.max(ReportTemplateVersion.version_number)).filter(
        ReportTemplateVersion.template_id == template.id,
        ReportTemplateVersion.is_deleted == False,
    ).scalar() or 0

    new_version_num = max_ver + 1

    ver = ReportTemplateVersion(
        template_id=template.id,
        version_number=new_version_num,
        html_content=data.html_content,
        css_content=data.css_content,
        header_html=data.header_html,
        footer_html=data.footer_html,
        status="DRAFT",
        change_notes=data.changelog or f"Version {new_version_num}",
        created_by=user.id,
    )
    db.add(ver)
    db.commit()
    db.refresh(ver)
    return ver


def publish_template_version(
    db: Session,
    template_id: int,
    version_id: int,
    user: User,
    org_context: OrgContext,
) -> ReportTemplate:
    """Sets a specific version as the active published version of the template."""
    template = get_template(db, template_id, org_context)

    if template.is_system:
        raise HTTPException(status_code=400, detail="System templates cannot be modified.")

    target_ver = db.query(ReportTemplateVersion).filter(
        ReportTemplateVersion.id == version_id,
        ReportTemplateVersion.template_id == template.id,
        ReportTemplateVersion.is_deleted == False,
    ).first()

    if not target_ver:
        raise HTTPException(status_code=404, detail="Template version not found.")

    # Mark previous published versions as ARCHIVED
    db.query(ReportTemplateVersion).filter(
        ReportTemplateVersion.template_id == template.id,
        ReportTemplateVersion.status == "PUBLISHED",
        ReportTemplateVersion.id != target_ver.id,
    ).update({"status": "ARCHIVED"})

    target_ver.status = "PUBLISHED"
    template.active_version_id = target_ver.id
    template.updated_by = user.id

    db.commit()
    db.refresh(template)
    return template

from sqlalchemy.orm import Session

from fastapi import HTTPException

from Model.containermgmt.Report.OrgPrintProfile import OrgPrintProfile
from Model.containermgmt.Report.ReportTemplate import ReportTemplate
from Model.containermgmt.Report.ReportTemplateAssignment import ReportTemplateAssignment
from Schema.ReportSchema import OrgPrintProfileUpdate, ReportTemplateAssignmentUpdate
from Utils.org_filter import OrgContext
from Utils.blob_storage import blob_storage


PRINT_ASSET_FIELDS = {
    "logo": "logo_asset_key",
    "stamp": "stamp_asset_key",
    "signature": "signature_asset_key",
}


def get_print_profile(db: Session, org_context: OrgContext) -> OrgPrintProfile:
    profile = db.query(OrgPrintProfile).filter(
        OrgPrintProfile.org_id == org_context.org_id,
        OrgPrintProfile.is_deleted.is_(False),
    ).first()
    if profile is None:
        profile = OrgPrintProfile(org_id=org_context.org_id)
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


def update_print_profile(
    db: Session,
    org_context: OrgContext,
    payload: OrgPrintProfileUpdate,
    user_id: int,
) -> OrgPrintProfile:
    profile = get_print_profile(db, org_context)
    for field, value in payload.model_dump().items():
        setattr(profile, field, value)
    profile.updated_by = user_id
    db.commit()
    db.refresh(profile)
    return profile


def upload_print_asset(
    db: Session,
    org_context: OrgContext,
    asset_type: str,
    content: bytes,
    filename: str,
    user_id: int,
) -> OrgPrintProfile:
    field = PRINT_ASSET_FIELDS.get(asset_type)
    if field is None:
        raise HTTPException(status_code=422, detail="Unsupported print asset type")
    key = blob_storage.upload_file(
        file_obj=content,
        folder=f"reports/org-{org_context.org_id}/{asset_type}",
        original_filename=filename,
    )
    profile = get_print_profile(db, org_context)
    setattr(profile, field, key)
    profile.updated_by = user_id
    db.commit()
    db.refresh(profile)
    return profile


def get_template_assignment(
    db: Session,
    org_context: OrgContext,
    template_id: int,
) -> ReportTemplateAssignment:
    template = db.query(ReportTemplate).filter(
        ReportTemplate.id == template_id,
        ReportTemplate.is_deleted.is_(False),
    ).first()
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")
    if not template.is_system and template.org_id != org_context.org_id:
        raise HTTPException(status_code=403, detail="Template belongs to another organisation")

    assignment = db.query(ReportTemplateAssignment).filter(
        ReportTemplateAssignment.org_id == org_context.org_id,
        ReportTemplateAssignment.template_id == template_id,
        ReportTemplateAssignment.is_deleted.is_(False),
    ).first()
    if assignment is None:
        assignment = ReportTemplateAssignment(
            org_id=org_context.org_id,
            template_id=template.id,
            entity_type=template.entity_type,
            is_active=False,
            is_default=False,
            default_options={},
        )
        db.add(assignment)
        db.commit()
        db.refresh(assignment)
    return assignment


def update_template_assignment(
    db: Session,
    org_context: OrgContext,
    template_id: int,
    payload: ReportTemplateAssignmentUpdate,
    user_id: int,
) -> ReportTemplateAssignment:
    assignment = get_template_assignment(db, org_context, template_id)
    values = payload.model_dump(exclude_unset=True)
    if values.get("is_default") is True:
        db.query(ReportTemplateAssignment).filter(
            ReportTemplateAssignment.org_id == org_context.org_id,
            ReportTemplateAssignment.entity_type == assignment.entity_type,
            ReportTemplateAssignment.id != assignment.id,
            ReportTemplateAssignment.is_deleted.is_(False),
        ).update({"is_default": False}, synchronize_session=False)
        values["is_active"] = True
    if values.get("is_active") is False:
        values["is_default"] = False
    for field, value in values.items():
        setattr(assignment, field, value)
    assignment.updated_by = user_id
    db.commit()
    db.refresh(assignment)
    return assignment

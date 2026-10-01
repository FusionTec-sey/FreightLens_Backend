"""
Routes/Reports/ReportRouter.py
FastAPI router for the Customer-Configurable Report & Print Template System.
Handles template CRUD, versioning, sandboxed Jinja2 rendering, WeasyPrint PDF compilation,
and AI Context File downloads.
"""
import io
import math
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from Model.db import get_db
from Model.containermgmt.Report.ReportTemplate import ReportTemplate
from Model.containermgmt.Report.ReportTemplateVersion import ReportTemplateVersion
from Model.Credentials.users import User
from auth.dependencies import get_current_user, get_org_context
from auth.security_guards import require_permission, has_permission, is_financial_user, can_view_supplier_user
from Utils.org_filter import OrgContext

from Schema.ReportDatasetSchema import (
    DatasetQuerySpec,
    DatasetResult,
    DatasetCatalogItem,
)
from Services.report_dataset_service import (
    list_dataset_catalog,
    get_dataset_resolver,
    run_dataset_query,
    export_dataset_excel,
    render_dataset_pdf,
)

from Schema.ReportSchema import (
    ReportTemplateCreate,
    ReportTemplateUpdate,
    ReportTemplateClone,
    ReportTemplateOut,
    ReportTemplateDetailOut,
    ReportTemplatePaginatedResponse,
    ReportTemplateVersionCreate,
    ReportTemplateVersionOut,
    ReportRenderRequest,
    ReportPreviewRequest,
    ReportValidateRequest,
    ReportValidateResponse,
    ResolverSchemaOut,
)
from Services.report_template_service import (
    list_templates,
    get_template,
    get_active_version_data,
    get_latest_version_data,
    create_custom_template,
    clone_template,
    update_template_metadata,
    delete_template,
    create_template_version,
    publish_template_version,
    list_active_templates_for_entity,
    toggle_template_activation,
)
from Services.report_data_resolvers import (
    list_resolvers,
    get_resolver,
    resolve_report_data,
)
from Services.report_template_validator import validate_template
from Services.report_render_engine import render_html_document, compile_pdf_from_html
from Services.report_context_generator import generate_context_file

logger = logging.getLogger("containerMgmt.report_router")

ReportRouter = APIRouter(prefix="/reports", tags=["Report Templates & Print Engine"])


def _apply_saved_dataset_template(
    report_key: str,
    spec: DatasetQuerySpec,
    db: Session,
    org_context: OrgContext,
) -> DatasetQuerySpec:
    if spec.template_id is None:
        return spec

    template = get_template(db, spec.template_id, org_context)
    if template.template_type != "OPERATIONAL_TABULAR" or template.resolver_key != report_key:
        raise HTTPException(status_code=422, detail="Saved template does not match this dataset")
    if not template.is_active_for_org:
        raise HTTPException(status_code=403, detail="Saved template is not active for this organisation")

    values = spec.model_dump()
    table = template.table_config or {}
    paper = template.paper_settings or {}
    values.update({
        "group_by": table.get("group_by") or values.get("group_by"),
        "sort_by": table.get("sort_by") or values.get("sort_by"),
        "sort_order": table.get("sort_order") or values.get("sort_order"),
        "layout_columns": table.get("columns") or values.get("layout_columns"),
        "page_size": paper.get("page_size") or values.get("page_size"),
        "orientation": paper.get("orientation") or values.get("orientation"),
        "margin_top": paper.get("margin_top") or values.get("margin_top"),
        "margin_bottom": paper.get("margin_bottom") or values.get("margin_bottom"),
        "margin_left": paper.get("margin_left") or values.get("margin_left"),
        "margin_right": paper.get("margin_right") or values.get("margin_right"),
        "repeat_header": paper.get("repeat_header", values.get("repeat_header")),
        "break_per_group": paper.get("break_per_group", values.get("break_per_group")),
        "sheet_per_group": paper.get("sheet_per_group", values.get("sheet_per_group")),
    })
    return DatasetQuerySpec.model_validate(values)


def _authorize_document_render(template, current_user: User, org_context: OrgContext):
    if org_context.selected_org_id is None and len(org_context.allowed_org_ids) > 1:
        raise HTTPException(status_code=400, detail="Select an organisation before rendering a document")
    if not template.is_active_for_org:
        raise HTTPException(status_code=403, detail="Report template is not active for this organisation")

    resolver = get_resolver(template.resolver_key)
    if not any(has_permission(current_user, permission) for permission in resolver.print_permissions):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing print permission for resolver '{resolver.key}'.",
        )
    return resolver


# ── Template Catalog & CRUD Endpoints ────────────────────────────────────────

@ReportRouter.get("/templates", response_model=ReportTemplatePaginatedResponse)
def get_templates_catalog(
    category: Optional[str] = Query(None, description="Filter by category: LOGISTICS, ORDERS, CROSS_MODULE"),
    template_type: Optional[str] = Query(None, description="Filter by template_type: DOCUMENT or OPERATIONAL_TABULAR"),
    entity_type: Optional[str] = Query(None, description="Filter by target entity_type: RFQ, PurchaseOrder, QuoteComparison, etc."),
    is_active: Optional[bool] = Query(None, description="Filter active status"),
    search: Optional[str] = Query(None, description="Search term for name or slug"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(25, ge=1, le=100, description="Items per page"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context),
):
    """Lists accessible report templates (both system defaults and tenant-customized templates)."""
    skip = (page - 1) * limit
    items, total = list_templates(
        db=db,
        org_context=org_context,
        category=category,
        is_active=is_active,
        search=search,
        template_type=template_type,
        entity_type=entity_type,
        skip=skip,
        limit=limit,
    )
    pages = math.ceil(total / limit) if limit > 0 else 1
    return {
        "items": items,
        "total": total,
        "page": page,
        "pages": pages,
        "limit": limit,
    }


@ReportRouter.get("/templates/by-entity", response_model=List[ReportTemplateOut])
def get_templates_by_entity(
    entity_type: str = Query(..., description="Target entity type: PurchaseOrder, ContainerDetails, BillOfLanding, etc."),
    template_type: str = Query("DOCUMENT", description="DOCUMENT or OPERATIONAL_TABULAR"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context),
):
    """
    Returns active templates for a given entity type in the current organization.
    Enforces user's rule: default system templates appear ONLY if activated in the Template Library.
    """
    return list_active_templates_for_entity(
        db=db,
        org_context=org_context,
        entity_type=entity_type,
        template_type=template_type,
    )


@ReportRouter.post("/templates/{template_id}/toggle-active")
def toggle_active_status(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context),
):
    """
    Toggles activation of a template for the current organization.
    For system templates: adds/removes org_id from active_org_ids.
    For custom templates: toggles is_active.
    """
    if not (
        has_permission(current_user, "Toggle_Report_Template")
        or has_permission(current_user, "Manage_Report_Template")
        or has_permission(current_user, "Manage_Operational_Template")
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing required permission 'Toggle_Report_Template'."
        )
    return toggle_template_activation(
        db=db,
        org_context=org_context,
        template_id=template_id,
        user=current_user,
    )


@ReportRouter.get("/templates/{template_id}", response_model=ReportTemplateDetailOut)
def get_template_detail(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context),
):
    """Retrieves full details of a template including active version content and version list."""
    template = get_template(db, template_id, org_context)
    active_ver = get_active_version_data(db, template)
    latest_ver = get_latest_version_data(db, template)
    if latest_ver and (not active_ver or latest_ver.version_number > active_ver.version_number):
        active_ver = latest_ver

    versions = (
        db.query(ReportTemplateVersion)
        .filter(
            ReportTemplateVersion.template_id == template.id,
            ReportTemplateVersion.is_deleted == False,
        )
        .order_by(ReportTemplateVersion.version_number.desc())
        .all()
    )

    detail = ReportTemplateDetailOut.model_validate(template)
    detail.active_version_data = ReportTemplateVersionOut.model_validate(active_ver) if active_ver else None
    detail.versions = [ReportTemplateVersionOut.model_validate(v) for v in versions]
    return detail


@ReportRouter.post("/templates", response_model=ReportTemplateOut, status_code=status.HTTP_201_CREATED)
def create_template(
    payload: ReportTemplateCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context),
):
    """Creates a new customer-defined report template."""
    if payload.template_type == "OPERATIONAL_TABULAR":
        if not (
            has_permission(current_user, "Manage_Operational_Template")
            or has_permission(current_user, "Manage_Report_Template")
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Missing required permission 'Manage_Operational_Template'."
            )
    else:
        if not has_permission(current_user, "Manage_Report_Template"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Missing required permission 'Manage_Report_Template'."
            )
    return create_custom_template(db, payload, current_user, org_context)


@ReportRouter.post("/templates/{template_id}/clone", response_model=ReportTemplateOut)
def clone_existing_template(
    template_id: int,
    payload: ReportTemplateClone,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context),
):
    """Clones a system template into a tenant-owned copy for customer customization."""
    if not (
        has_permission(current_user, "Manage_Report_Template")
        or has_permission(current_user, "Manage_Operational_Template")
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing required permission 'Manage_Report_Template'."
        )
    return clone_template(db, template_id, payload, current_user, org_context)


@ReportRouter.put("/templates/{template_id}", response_model=ReportTemplateOut)
def update_template(
    template_id: int,
    payload: ReportTemplateUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context),
):
    """Updates metadata on a tenant-owned template."""
    if not (
        has_permission(current_user, "Manage_Report_Template")
        or has_permission(current_user, "Manage_Operational_Template")
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing required permission 'Manage_Report_Template' or 'Manage_Operational_Template'."
        )
    return update_template_metadata(db, template_id, payload, current_user, org_context)


@ReportRouter.delete("/templates/{template_id}")
def delete_existing_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context),
):
    """Soft-deletes a tenant-owned template."""
    if not (
        has_permission(current_user, "Manage_Report_Template")
        or has_permission(current_user, "Manage_Operational_Template")
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing required permission 'Manage_Report_Template' or 'Manage_Operational_Template'."
        )
    delete_template(db, template_id, current_user, org_context)
    return {"message": "Report template deleted successfully."}


# ── Version Management Endpoints ─────────────────────────────────────────────

@ReportRouter.get("/templates/{template_id}/versions", response_model=List[ReportTemplateVersionOut])
def list_template_versions(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context),
):
    """Lists all versions belonging to a template."""
    template = get_template(db, template_id, org_context)
    versions = (
        db.query(ReportTemplateVersion)
        .filter(
            ReportTemplateVersion.template_id == template.id,
            ReportTemplateVersion.is_deleted == False,
        )
        .order_by(ReportTemplateVersion.version_number.desc())
        .all()
    )
    return versions


@ReportRouter.post("/templates/{template_id}/versions", response_model=ReportTemplateVersionOut, status_code=status.HTTP_201_CREATED)
def create_new_template_version(
    template_id: int,
    payload: ReportTemplateVersionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context),
):
    """Creates a new draft version for a tenant-owned template."""
    if not (
        has_permission(current_user, "Manage_Report_Template")
        or has_permission(current_user, "Manage_Operational_Template")
    ):
        raise HTTPException(status_code=403, detail="Missing template management permission")
    return create_template_version(db, template_id, payload, current_user, org_context)


@ReportRouter.put("/templates/{template_id}/versions/{version_id}/publish", response_model=ReportTemplateOut)
def publish_version(
    template_id: int,
    version_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context),
):
    """Activates and publishes a specific version of a template."""
    if not (
        has_permission(current_user, "Manage_Report_Template")
        or has_permission(current_user, "Manage_Operational_Template")
    ):
        raise HTTPException(status_code=403, detail="Missing template management permission")
    return publish_template_version(db, template_id, version_id, current_user, org_context)


@ReportRouter.post("/templates/validate", response_model=ReportValidateResponse)
def validate_template_code(
    payload: ReportValidateRequest,
    current_user: User = Depends(get_current_user),
):
    """Pre-save syntax and security validation for HTML and CSS templates."""
    is_valid, errors, warnings = validate_template(
        html_content=payload.html_content,
        css_content=payload.css_content,
        header_html=payload.header_html,
        footer_html=payload.footer_html,
        resolver_key=payload.resolver_key,
    )
    return {"is_valid": is_valid, "errors": errors, "warnings": warnings}


# ── Report Rendering Pipeline ────────────────────────────────────────────────

@ReportRouter.post("/render")
def render_report_pdf(
    req: ReportRenderRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context),
):
    """
    Renders a report to a binary PDF stream using sandboxed Jinja2 and WeasyPrint.
    Returns: application/pdf binary stream.
    """
    template = None
    if req.template_id:
        template = get_template(db, req.template_id, org_context)
    elif req.template_slug:
        # Search tenant template first, then system template
        template = (
            db.query(ReportTemplate)
            .filter(
                ReportTemplate.slug == req.template_slug,
                ReportTemplate.org_id.in_(org_context.allowed_org_ids),
                ReportTemplate.is_deleted == False,
            )
            .first()
        )
        if not template:
            template = (
                db.query(ReportTemplate)
                .filter(
                    ReportTemplate.slug == req.template_slug,
                    ReportTemplate.is_system == True,
                    ReportTemplate.is_deleted == False,
                )
                .first()
            )
    
    if not template:
        raise HTTPException(status_code=404, detail="Requested report template was not found.")

    _authorize_document_render(template, current_user, org_context)

    version = get_active_version_data(db, template)
    if not version:
        raise HTTPException(status_code=400, detail="The specified report template has no published version to render.")

    # Resolve context data
    context = resolve_report_data(
        resolver_key=template.resolver_key,
        entity_id=req.entity_id,
        db=db,
        org_context=org_context,
        user=current_user,
        params=req.params,
    )

    # Render HTML
    full_html = render_html_document(
        html_template=version.html_content,
        context=context,
        css_content=version.css_content,
        header_template=version.header_html,
        footer_template=version.footer_html,
        page_size=template.page_size or "A4",
        orientation=template.orientation or "portrait",
    )

    # If requested format is html, return rendered HTML directly
    if req.format and req.format.lower() == "html":
        return Response(content=full_html, media_type="text/html; charset=utf-8")

    # Compile PDF via WeasyPrint
    pdf_bytes = compile_pdf_from_html(full_html)
    filename = f"{template.slug}_{req.entity_id}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@ReportRouter.post("/render/preview")
def render_report_preview(
    req: ReportPreviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context),
):
    """
    Renders an HTML preview of a report. Supports both saved templates and unsaved
    live editor snippets with realistic sample data.
    """
    html_content = req.html_content
    css_content = req.css_content
    header_html = req.header_html
    footer_html = req.footer_html
    resolver_key = req.resolver_key
    page_size = "A4"
    orientation = "portrait"

    if req.template_id:
        template = get_template(db, req.template_id, org_context)
        resolver_key = template.resolver_key
        page_size = template.page_size or "A4"
        orientation = template.orientation or "portrait"
        
        # If user did not pass code override, use template's active version
        if not html_content:
            version = get_active_version_data(db, template)
            if version:
                html_content = version.html_content
                css_content = version.css_content
                header_html = version.header_html
                footer_html = version.footer_html

    if not html_content:
        raise HTTPException(status_code=400, detail="No HTML template content provided for preview.")

    if not resolver_key:
        raise HTTPException(status_code=400, detail="resolver_key is required to resolve preview context data.")

    is_valid, errors, _ = validate_template(
        html_content=html_content,
        css_content=css_content,
        header_html=header_html,
        footer_html=footer_html,
        resolver_key=resolver_key,
    )
    if not is_valid:
        raise HTTPException(status_code=422, detail={"message": "Unsafe report preview", "errors": errors})

    context = resolve_report_data(
        resolver_key=resolver_key,
        entity_id=req.entity_id,
        db=db,
        org_context=org_context,
        user=current_user,
        params=req.params,
    )

    full_html = render_html_document(
        html_template=html_content,
        context=context,
        css_content=css_content,
        header_template=header_html,
        footer_template=footer_html,
        page_size=page_size,
        orientation=orientation,
    )

    return {"html": full_html}


# ── Resolvers & AI Context File System ───────────────────────────────────────

@ReportRouter.get("/resolvers", summary="List all registered data resolvers")
def get_registered_resolvers(
    category: Optional[str] = Query(None, description="Filter resolvers by category"),
    current_user: User = Depends(get_current_user),
):
    """Lists available data resolvers and high-level descriptions."""
    return {"resolvers": list_resolvers(category)}


@ReportRouter.get("/resolvers/{resolver_key}/schema", response_model=ResolverSchemaOut)
def get_resolver_schema(
    resolver_key: str,
    current_user: User = Depends(require_permission("Manage_Report_Template")),
):
    """Returns field definitions and sample context for a resolver."""
    resolver = get_resolver(resolver_key)
    return {
        "resolver_key": resolver.key,
        "name": resolver.name,
        "entity_type": resolver.entity_type,
        "category": resolver.category,
        "description": resolver.description,
        "fields": resolver.schema_meta,
        "sample_context": resolver.sample_context,
    }


@ReportRouter.get("/resolvers/{resolver_key}/context-file")
def download_ai_context_file(
    resolver_key: str,
    current_user: User = Depends(require_permission("Manage_Report_Template")),
):
    """
    Downloads an AI Developer Context Markdown file (.md).
    Users can paste this file into external LLMs (ChatGPT, Claude, Cursor) to generate templates.
    """
    md_content = generate_context_file(resolver_key)
    filename = f"freightlens_context_{resolver_key}.md"
    return Response(
        content=md_content,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Dataset & Tabular Operational Registers ──────────────────────────────────

@ReportRouter.get("/datasets", response_model=List[DatasetCatalogItem])
def get_dataset_reports_catalog(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context),
):
    """Lists all operational dataset reports and registers available to the user."""
    if not (
        has_permission(current_user, "View_Operational_Register")
        or has_permission(current_user, "View_Report")
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing required permission 'View_Operational_Register'."
        )
    return list_dataset_catalog(current_user, org_context)


@ReportRouter.get("/datasets/{report_key}/schema", response_model=DatasetCatalogItem)
def get_dataset_report_schema(
    report_key: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context),
):
    """Returns the filter definitions, columns, and sort/group options for a dataset report."""
    if not (
        has_permission(current_user, "View_Operational_Register")
        or has_permission(current_user, "View_Report")
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing required permission 'View_Operational_Register'."
        )
    resolver = get_dataset_resolver(report_key)
    can_financial = is_financial_user(current_user, org_context)
    can_vendor = can_view_supplier_user(current_user, org_context)

    filtered_cols = [
        c for c in resolver.columns
        if not (c.restricted_permission == "View_Financials" and not can_financial)
        and not (c.restricted_permission == "View_Supplier" and not can_vendor)
    ]
    return DatasetCatalogItem(
        key=resolver.key,
        name=resolver.name,
        category=resolver.category,
        description=resolver.description,
        default_orientation=resolver.default_orientation,
        default_page_size=resolver.default_page_size,
        supported_filters=resolver.filters,
        supported_sort_fields=resolver.sort_fields,
        supported_group_fields=resolver.group_fields,
        columns=filtered_cols,
    )


@ReportRouter.post("/datasets/{report_key}/run", response_model=DatasetResult)
def run_dataset_report_query(
    report_key: str,
    spec: DatasetQuerySpec,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context),
):
    """Executes a parametric query for an operational report and returns paginated records with subtotals."""
    if not (
        has_permission(current_user, "Run_Operational_Register")
        or has_permission(current_user, "View_Report")
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing required permission 'Run_Operational_Register'."
        )
    spec = _apply_saved_dataset_template(report_key, spec, db, org_context)
    return run_dataset_query(report_key, spec, db, org_context, current_user)


@ReportRouter.post("/datasets/{report_key}/render")
def render_dataset_report_pdf(
    report_key: str,
    spec: DatasetQuerySpec,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context),
):
    """Compiles the operational register into an enterprise landscape PDF with repeating headers."""
    if not (
        has_permission(current_user, "Run_Operational_Register")
        or has_permission(current_user, "View_Report")
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing required permission 'Run_Operational_Register'."
        )
    spec = _apply_saved_dataset_template(report_key, spec, db, org_context)
    spec = spec.model_copy(update={"format": "pdf"})
    pdf_bytes = render_dataset_pdf(report_key, spec, db, org_context, current_user)
    filename = f"{report_key}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@ReportRouter.post("/datasets/{report_key}/export")
def export_dataset_report_excel(
    report_key: str,
    spec: DatasetQuerySpec,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    org_context: OrgContext = Depends(get_org_context),
):
    """Generates and streams a styled Excel (.xlsx) spreadsheet with subtotals and auto-fitted columns."""
    if not (
        has_permission(current_user, "Run_Operational_Register")
        or has_permission(current_user, "View_Report")
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing required permission 'Run_Operational_Register'."
        )
    spec = _apply_saved_dataset_template(report_key, spec, db, org_context)
    spec = spec.model_copy(update={"format": "xlsx"})
    excel_bytes = export_dataset_excel(report_key, spec, db, org_context, current_user)
    filename = f"{report_key}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return StreamingResponse(
        io.BytesIO(excel_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


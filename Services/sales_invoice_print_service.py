"""Immutable sales-invoice artifacts and explicit physical print outcomes."""
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from types import SimpleNamespace
from uuid import UUID

from sqlalchemy import func, or_

from Model.containermgmt.Orders.SalesInvoicePrint import (
    SalesInvoiceArtifact, SalesInvoicePrintEvent, SalesInvoicePrintJob,
)
from Model.containermgmt.Orders.SalesPosting import SalesInvoice
from Model.containermgmt.Report.OrgPrintProfile import OrgPrintProfile
from Model.containermgmt.Report.ReportTemplate import ReportTemplate
from Model.containermgmt.Report.ReportTemplateAssignment import ReportTemplateAssignment
from Model.containermgmt.Report.ReportTemplateVersion import ReportTemplateVersion
from Services.inventory_posting_service import PostingConflict, PostingEffect, execute_once
from Services.report_data_resolvers import resolve_sales_invoice
from Services.report_render_engine import compile_pdf_from_html, render_html_document
from Utils.blob_storage import blob_storage
from Utils.org_filter import apply_org_filter


MAX_INVOICE_PDF_BYTES = 10 * 1024 * 1024


def _owned(db, model, context):
    return apply_org_filter(db.query(model).filter(
        model.org_id == context.org_id, model.is_deleted.is_(False)), model, context)


def _guard(context, authorize, db):
    if context.org_id not in context.allowed_org_ids:
        raise PermissionError("Invoice print company scope denied")
    if not callable(authorize):
        raise ValueError("Invoice print authorization guard required")
    authorize(db)


def _digest(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True, allow_nan=False)
    return sha256(encoded.encode("utf-8")).hexdigest()


def _template_choice(db, context):
    rows = db.query(ReportTemplateAssignment, ReportTemplate, ReportTemplateVersion).join(
        ReportTemplate, ReportTemplate.id == ReportTemplateAssignment.template_id).join(
        ReportTemplateVersion, ReportTemplateVersion.id == ReportTemplate.active_version_id).filter(
        ReportTemplateAssignment.org_id == context.org_id,
        ReportTemplateAssignment.entity_type == "SalesInvoice",
        ReportTemplateAssignment.is_active.is_(True),
        ReportTemplateAssignment.is_default.is_(True),
        ReportTemplateAssignment.is_deleted.is_(False),
        ReportTemplate.is_active.is_(True),
        ReportTemplate.is_deleted.is_(False),
        ReportTemplate.resolver_key == "sales_invoice",
        ReportTemplate.entity_type == "SalesInvoice",
        or_(ReportTemplate.is_system.is_(True), ReportTemplate.org_id == context.org_id),
        ReportTemplateVersion.template_id == ReportTemplate.id,
        ReportTemplateVersion.status == "PUBLISHED",
        ReportTemplateVersion.is_deleted.is_(False),
    ).all()
    if len(rows) != 1:
        raise PostingConflict("Configure one active default sales-invoice template")
    return rows[0]


def _artifact_dict(row):
    return {
        "artifact_key": str(row.artifact_key), "invoice_key": str(row.invoice_key),
        "template_id": row.template_id, "template_version_id": row.template_version_id,
        "artifact_kind": row.artifact_kind, "copy_number": row.copy_number,
        "source_artifact_key": str(row.source_artifact_key) if row.source_artifact_key else None,
        "pdf_sha256": row.pdf_sha256, "file_size": row.file_size,
        "created_at": row.created_at.isoformat(),
    }


def _job_dict(db, context, row):
    artifact = _owned(db, SalesInvoiceArtifact, context).filter_by(
        artifact_key=row.artifact_key).one()
    events = _owned(db, SalesInvoicePrintEvent, context).filter_by(
        job_key=row.job_key).order_by(SalesInvoicePrintEvent.sequence).all()
    return {
        "job_key": str(row.job_key), "artifact": _artifact_dict(artifact),
        "status": row.status, "version": row.version,
        "handed_off_at": row.handed_off_at.isoformat() if row.handed_off_at else None,
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
        "resolved_by": row.resolved_by, "failure_code": row.failure_code,
        "resolution_note": row.resolution_note,
        "events": [{"sequence": event.sequence, "from_status": event.from_status,
                    "to_status": event.to_status, "note": event.note,
                    "created_at": event.created_at.isoformat(),
                    "created_by": event.created_by} for event in events],
    }


def _open_job_for_invoice(db, context, invoice_key):
    return _owned(db, SalesInvoicePrintJob, context).join(
        SalesInvoiceArtifact,
        (SalesInvoiceArtifact.org_id == SalesInvoicePrintJob.org_id) &
        (SalesInvoiceArtifact.artifact_key == SalesInvoicePrintJob.artifact_key)).filter(
        SalesInvoiceArtifact.invoice_key == invoice_key,
        SalesInvoicePrintJob.status.in_(("READY", "UNCERTAIN"))).first()


def read_print_options(db, context, invoice_key, *, authorize):
    _guard(context, authorize, db)
    invoice = _owned(db, SalesInvoice, context).filter_by(
        invoice_key=UUID(str(invoice_key))).one_or_none()
    if invoice is None:
        raise LookupError("Sales invoice not found")
    _, template, version = _template_choice(db, context)
    original = _owned(db, SalesInvoiceArtifact, context).filter_by(
        invoice_key=invoice.invoice_key, artifact_kind="ORIGINAL").one_or_none()
    return {
        "invoice_key": str(invoice.invoice_key), "invoice_number": invoice.invoice_number,
        "template_id": template.id, "template_version_id": version.id,
        "template_name": template.name,
        "original_artifact": _artifact_dict(original) if original else None,
    }


def read_print_job(db, context, job_key, *, authorize):
    _guard(context, authorize, db)
    row = _owned(db, SalesInvoicePrintJob, context).filter_by(
        job_key=UUID(str(job_key))).one_or_none()
    if row is None:
        raise LookupError("Invoice print job not found")
    return _job_dict(db, context, row)


def list_invoice_print_jobs(db, context, invoice_key, page, limit, *, authorize):
    _guard(context, authorize, db)
    if page < 1 or not 1 <= limit <= 100:
        raise ValueError("Invalid print history page")
    invoice = _owned(db, SalesInvoice, context).filter_by(
        invoice_key=UUID(str(invoice_key))).one_or_none()
    if invoice is None:
        raise LookupError("Sales invoice not found")
    query = _owned(db, SalesInvoicePrintJob, context).join(
        SalesInvoiceArtifact,
        (SalesInvoiceArtifact.org_id == SalesInvoicePrintJob.org_id) &
        (SalesInvoiceArtifact.artifact_key == SalesInvoicePrintJob.artifact_key)).filter(
        SalesInvoiceArtifact.invoice_key == invoice.invoice_key)
    total = query.count()
    rows = query.order_by(SalesInvoicePrintJob.created_at.desc(),
                          SalesInvoicePrintJob.job_key.desc()).offset(
        (page - 1) * limit).limit(limit).all()
    return {"items": [_job_dict(db, context, row) for row in rows],
            "page": page, "pages": math.ceil(total / limit) if total else 1,
            "limit": limit, "total": total}


def _copy_overlay(number):
    return ("<div aria-label=\"COPY\" style=\"position:fixed;z-index:2147483647;"
            "right:12mm;top:8mm;border:2px solid #b91c1c;color:#b91c1c;"
            "background:white;padding:3mm;font:800 18pt Arial\">"
            f"COPY {number}</div>")


def _full_html(template_snapshot, data, copy_number):
    html = render_html_document(
        template_snapshot["html_content"], data,
        css_content=template_snapshot.get("css_content"),
        header_template=template_snapshot.get("header_html"),
        footer_template=template_snapshot.get("footer_html"),
        page_size=template_snapshot["page_size"],
        orientation=template_snapshot["orientation"],
    )
    if copy_number:
        marker = _copy_overlay(copy_number)
        html = html.replace("<body>", f"<body>{marker}", 1)
    return html


def create_invoice_print_job(session_factory, context, actor_id, payload, *,
        authorize, storage=blob_storage, pdf_renderer=compile_pdf_from_html):
    request = {
        "job_key": str(payload.job_key), "artifact_key": str(payload.artifact_key),
        "invoice_key": str(payload.invoice_key), "kind": payload.kind,
        "expected_template_id": payload.expected_template_id,
        "expected_template_version_id": payload.expected_template_version_id,
        "source_artifact_key": str(payload.source_artifact_key) if payload.source_artifact_key else None,
    }

    # A completed retry must not generate another external object.
    with session_factory() as check:
        with check.begin():
            _guard(context, authorize, check)
            existing = _owned(check, SalesInvoiceArtifact, context).filter_by(
                operation_key=payload.operation_key).one_or_none()
            if existing is not None:
                def impossible(_db):
                    raise PostingConflict("Print replay receipt is incomplete")
                return execute_once(check, context, actor_id, payload.operation_key,
                    "sales.invoice.print.request.v1", request, impossible,
                    authorize=authorize)

    with session_factory() as prepare:
        with prepare.begin():
            _guard(context, authorize, prepare)
            invoice = _owned(prepare, SalesInvoice, context).filter_by(
                invoice_key=payload.invoice_key).one_or_none()
            if invoice is None:
                raise LookupError("Sales invoice not found")
            if _open_job_for_invoice(prepare, context, invoice.invoice_key) is not None:
                raise PostingConflict("Resolve the current invoice print job before creating another")
            if payload.kind == "ORIGINAL":
                _, template, version = _template_choice(prepare, context)
                if (payload.expected_template_id != template.id or
                        payload.expected_template_version_id != version.id):
                    raise PostingConflict("Invoice template changed; reload before printing")
                profile = prepare.query(OrgPrintProfile).filter_by(
                    org_id=context.org_id, is_deleted=False).one_or_none()
                if profile is None or any(not str(getattr(profile, name) or "").strip()
                                          for name in ("legal_name", "address", "tax_id")):
                    raise PostingConflict("Legal name, address and tax ID are required for invoices")
                data = resolve_sales_invoice(invoice.invoice_key, prepare, context,
                                             SimpleNamespace(id=actor_id), {})
                template_snapshot = {
                    "template_id": template.id, "template_version_id": version.id,
                    "html_content": version.html_content, "css_content": version.css_content,
                    "header_html": version.header_html, "footer_html": version.footer_html,
                    "page_size": template.page_size or "A4",
                    "orientation": template.orientation or "portrait",
                    "renderer": "freightlens-weasyprint-v1",
                }
                copy_number, source_key = 0, None
            else:
                source = _owned(prepare, SalesInvoiceArtifact, context).filter_by(
                    artifact_key=payload.source_artifact_key,
                    invoice_key=payload.invoice_key, artifact_kind="ORIGINAL").one_or_none()
                if source is None:
                    raise PostingConflict("COPY requires this invoice's immutable original")
                frozen = dict(source.data_snapshot)
                data = frozen["data"]
                template_snapshot = frozen["template"]
                copy_number, source_key = None, source.artifact_key

    # COPY numbering is revalidated and allocated under the invoice lock below;
    # this tentative number only renders the bytes. A conflict discards the
    # unreferenced object and the caller retries with a new operation.
    if copy_number is None:
        with session_factory() as number_db:
            with number_db.begin():
                maximum = _owned(number_db, SalesInvoiceArtifact, context).filter_by(
                    invoice_key=payload.invoice_key).with_entities(
                    func.max(SalesInvoiceArtifact.copy_number)).scalar()
                copy_number = int(maximum or 0) + 1
    snapshot = {"data": data, "template": template_snapshot}
    html = _full_html(template_snapshot, data, copy_number)
    pdf = pdf_renderer(html)
    if not isinstance(pdf, bytes) or not 0 < len(pdf) <= MAX_INVOICE_PDF_BYTES:
        raise ValueError("Invoice PDF is empty or exceeds the ten MiB limit")
    pdf_digest = sha256(pdf).hexdigest()
    object_key = storage.upload_file(pdf,
        folder=f"sales-invoices/org-{context.org_id}/invoice-{payload.invoice_key}",
        original_filename=("invoice-original.pdf" if copy_number == 0
                           else f"invoice-copy-{copy_number}.pdf"))
    fingerprint = storage.fingerprint_file_version(
        object_key, max_bytes=MAX_INVOICE_PDF_BYTES)
    if (fingerprint.get("policy") != "blob-sha256-v1" or
            fingerprint.get("object_key") != object_key or
            fingerprint.get("sha256") != pdf_digest or
            fingerprint.get("size") != len(pdf)):
        raise PostingConflict("Durable invoice object verification failed")

    def apply(db):
        invoice = _owned(db, SalesInvoice, context).filter_by(
            invoice_key=payload.invoice_key).with_for_update().one_or_none()
        if invoice is None:
            raise LookupError("Sales invoice not found")
        if _open_job_for_invoice(db, context, invoice.invoice_key) is not None:
            raise PostingConflict("Resolve the current invoice print job before creating another")
        if payload.kind == "ORIGINAL":
            if _owned(db, SalesInvoiceArtifact, context).filter_by(
                    invoice_key=invoice.invoice_key, artifact_kind="ORIGINAL").one_or_none():
                raise PostingConflict("The invoice original already exists")
            _, current_template, current_version = _template_choice(db, context)
            current_template_snapshot = {
                "template_id": current_template.id,
                "template_version_id": current_version.id,
                "html_content": current_version.html_content,
                "css_content": current_version.css_content,
                "header_html": current_version.header_html,
                "footer_html": current_version.footer_html,
                "page_size": current_template.page_size or "A4",
                "orientation": current_template.orientation or "portrait",
                "renderer": "freightlens-weasyprint-v1",
            }
            profile = db.query(OrgPrintProfile).filter_by(
                org_id=context.org_id, is_deleted=False).with_for_update().one_or_none()
            current_data = resolve_sales_invoice(invoice.invoice_key, db, context,
                SimpleNamespace(id=actor_id), {})
            if (current_template_snapshot != template_snapshot or
                    current_data != data):
                raise PostingConflict("Invoice print configuration changed during rendering")
        else:
            source = _owned(db, SalesInvoiceArtifact, context).filter_by(
                artifact_key=source_key, invoice_key=invoice.invoice_key,
                artifact_kind="ORIGINAL").with_for_update().one_or_none()
            if source is None or source.data_snapshot != snapshot:
                raise PostingConflict("Invoice original changed during COPY rendering")
            maximum = _owned(db, SalesInvoiceArtifact, context).filter_by(
                invoice_key=invoice.invoice_key).with_entities(
                func.max(SalesInvoiceArtifact.copy_number)).scalar()
            if copy_number != int(maximum or 0) + 1:
                raise PostingConflict("COPY sequence changed; retry the same request")
        artifact = SalesInvoiceArtifact(
            org_id=context.org_id, artifact_key=payload.artifact_key,
            operation_key=payload.operation_key, invoice_key=invoice.invoice_key,
            template_id=template_snapshot["template_id"],
            template_version_id=template_snapshot["template_version_id"],
            artifact_kind=payload.kind, copy_number=copy_number,
            source_artifact_key=source_key, data_snapshot=snapshot,
            snapshot_sha256=_digest(snapshot), html_sha256=sha256(html.encode()).hexdigest(),
            pdf_sha256=pdf_digest, object_key=object_key, file_size=len(pdf),
            storage_fingerprint=fingerprint, created_by=actor_id)
        job = SalesInvoicePrintJob(
            org_id=context.org_id, job_key=payload.job_key,
            operation_key=payload.operation_key, artifact_key=payload.artifact_key,
            status="READY", version=1, created_by=actor_id)
        event = SalesInvoicePrintEvent(
            org_id=context.org_id, job_key=payload.job_key,
            operation_key=payload.operation_key, sequence=1, from_status=None,
            to_status="READY", note="Durable PDF ready for print handoff",
            created_by=actor_id)
        db.add(artifact)
        db.flush()
        db.add(job)
        db.flush()
        db.add(event)
        db.flush()
        result = _job_dict(db, context, job)
        return PostingEffect(result=result,
            event={"type": "sales.invoice.print.ready.v1",
                   "invoice_key": str(invoice.invoice_key),
                   "job_key": str(job.job_key), "artifact_key": str(artifact.artifact_key)})

    return execute_once(session_factory, context, actor_id, payload.operation_key,
        "sales.invoice.print.request.v1", request, apply, authorize=authorize)


def handoff_print_job(session_factory, context, actor_id, job_key, payload, *, authorize):
    request = {"job_key": str(job_key), "expected_version": payload.expected_version}
    def apply(db):
        row = _owned(db, SalesInvoicePrintJob, context).filter_by(
            job_key=UUID(str(job_key))).with_for_update().one_or_none()
        if row is None:
            raise LookupError("Invoice print job not found")
        if row.version != payload.expected_version or row.status != "READY":
            raise PostingConflict("Print job changed; reload before handoff")
        row.status, row.version = "UNCERTAIN", row.version + 1
        row.handed_off_at = datetime.now(timezone.utc)
        row.updated_by = actor_id
        db.add(SalesInvoicePrintEvent(org_id=context.org_id, job_key=row.job_key,
            operation_key=payload.operation_key, sequence=row.version,
            from_status="READY", to_status="UNCERTAIN",
            note="PDF handed to an untrusted physical print path", created_by=actor_id))
        db.flush()
        return PostingEffect(result=_job_dict(db, context, row),
            event={"type": "sales.invoice.print.handed_off.v1", "job_key": str(row.job_key)})
    return execute_once(session_factory, context, actor_id, payload.operation_key,
        "sales.invoice.print.handoff.v1", request, apply, authorize=authorize)


def resolve_print_job(session_factory, context, actor_id, job_key, payload, *, authorize):
    request = {"job_key": str(job_key), "expected_version": payload.expected_version,
               "outcome": payload.outcome, "failure_code": payload.failure_code,
               "note": payload.note}
    def apply(db):
        row = _owned(db, SalesInvoicePrintJob, context).filter_by(
            job_key=UUID(str(job_key))).with_for_update().one_or_none()
        if row is None:
            raise LookupError("Invoice print job not found")
        if row.version != payload.expected_version:
            raise PostingConflict("Print job changed; reload before resolving")
        if payload.outcome == "PRINTED" and row.status != "UNCERTAIN":
            raise PostingConflict("Only a handed-off print can be confirmed printed")
        if payload.outcome == "FAILED" and row.status not in ("READY", "UNCERTAIN"):
            raise PostingConflict("Only an open print job can fail")
        previous = row.status
        row.status, row.version = payload.outcome, row.version + 1
        row.resolved_at, row.resolved_by = datetime.now(timezone.utc), actor_id
        row.failure_code, row.resolution_note = payload.failure_code, payload.note
        row.updated_by = actor_id
        db.add(SalesInvoicePrintEvent(org_id=context.org_id, job_key=row.job_key,
            operation_key=payload.operation_key, sequence=row.version,
            from_status=previous, to_status=payload.outcome,
            note=payload.note, created_by=actor_id))
        db.flush()
        return PostingEffect(result=_job_dict(db, context, row),
            event={"type": "sales.invoice.print.resolved.v1", "job_key": str(row.job_key),
                   "outcome": payload.outcome})
    return execute_once(session_factory, context, actor_id, payload.operation_key,
        "sales.invoice.print.resolve.v1", request, apply, authorize=authorize)


def read_artifact_bytes(db, context, artifact_key, *, authorize, storage=blob_storage):
    _guard(context, authorize, db)
    row = _owned(db, SalesInvoiceArtifact, context).filter_by(
        artifact_key=UUID(str(artifact_key))).one_or_none()
    if row is None:
        raise LookupError("Invoice artifact not found")
    content = storage.read_verified_file_version(
        dict(row.storage_fingerprint), max_bytes=MAX_INVOICE_PDF_BYTES)
    if sha256(content).hexdigest() != row.pdf_sha256 or len(content) != row.file_size:
        raise PostingConflict("Invoice artifact verification failed")
    return row, content

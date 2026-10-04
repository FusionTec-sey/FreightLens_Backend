import hashlib
import json
import logging
import multiprocessing
import os
import socket
import time
from datetime import datetime, timedelta, timezone
from queue import Empty
from typing import Callable

from sqlalchemy import or_
from sqlalchemy.orm import Session

from Model.Credentials.users import User
from Model.containermgmt.Report.ReportRenderJob import ReportRenderJob
from Model.containermgmt.Report.ReportTemplate import ReportTemplate
from Model.containermgmt.Report.ReportTemplateVersion import ReportTemplateVersion
from Model.db import SessionLocal
from Services.report_data_resolvers import resolve_report_data
from Services.report_audit_service import render_is_issued
from Utils.blob_storage import blob_storage
from Utils.org_filter import OrgContext
from auth.policy import get_access_policy


logger = logging.getLogger("containerMgmt.reporting.worker")
DEFAULT_RENDER_TIMEOUT_SECONDS = 45
DEFAULT_LEASE_SECONDS = 120


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _render_pdf_child(payload: dict, result_queue) -> None:
    try:
        from Services.report_render_engine import compile_pdf_from_html, render_html_document

        html = render_html_document(
            html_template=payload["html_content"],
            context=payload["context"],
            css_content=payload.get("css_content"),
            header_template=payload.get("header_html"),
            footer_template=payload.get("footer_html"),
            page_size=payload.get("page_size") or "A4",
            orientation=payload.get("orientation") or "portrait",
        )
        result_queue.put((True, compile_pdf_from_html(html)))
    except Exception as exc:
        result_queue.put((False, f"{type(exc).__name__}: {exc}"))


def render_pdf_with_timeout(payload: dict, timeout_seconds: int) -> bytes:
    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue(maxsize=1)
    process = context.Process(target=_render_pdf_child, args=(payload, result_queue))
    process.start()
    process.join(timeout_seconds)
    if process.is_alive():
        process.terminate()
        process.join(5)
        raise TimeoutError(f"Report rendering exceeded {timeout_seconds} seconds")
    try:
        succeeded, result = result_queue.get(timeout=1)
    except Empty as exc:
        raise RuntimeError(f"Render process exited without a result (code {process.exitcode})") from exc
    finally:
        result_queue.close()
    if not succeeded:
        raise RuntimeError(result)
    return result


class ReportRenderWorker:
    def __init__(
        self,
        *,
        worker_id: str | None = None,
        timeout_seconds: int = DEFAULT_RENDER_TIMEOUT_SECONDS,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        render_pdf: Callable[[dict, int], bytes] = render_pdf_with_timeout,
    ) -> None:
        self.worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}"
        self.timeout_seconds = timeout_seconds
        self.lease_seconds = lease_seconds
        self.render_pdf = render_pdf

    def claim_next(self, db: Session) -> ReportRenderJob | None:
        now = _utcnow()
        job = (
            db.query(ReportRenderJob)
            .filter(
                or_(
                    ReportRenderJob.status == "PENDING",
                    (ReportRenderJob.status == "RENDERING")
                    & (ReportRenderJob.lease_expires_at < now),
                ),
                or_(ReportRenderJob.retry_at.is_(None), ReportRenderJob.retry_at <= now),
                ReportRenderJob.attempt_count < ReportRenderJob.max_attempts,
            )
            .order_by(ReportRenderJob.requested_at.asc())
            .with_for_update(skip_locked=True)
            .first()
        )
        if job is None:
            db.rollback()
            return None
        job.status = "RENDERING"
        job.worker_id = self.worker_id
        job.started_at = now
        job.heartbeat_at = now
        job.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
        job.attempt_count += 1
        job.error_message = None
        db.commit()
        db.refresh(job)
        return job

    def process(self, db: Session, job: ReportRenderJob) -> None:
        job_id = job.id
        try:
            template = db.query(ReportTemplate).filter(
                ReportTemplate.id == job.template_id,
                or_(ReportTemplate.org_id == job.org_id, ReportTemplate.is_system.is_(True)),
                ReportTemplate.is_deleted.is_(False),
                ReportTemplate.is_active.is_(True),
            ).first()
            if template is None:
                raise RuntimeError("Render template is unavailable for the job organisation")
            version = db.query(ReportTemplateVersion).filter(
                ReportTemplateVersion.id == job.version_id,
                ReportTemplateVersion.template_id == template.id,
                ReportTemplateVersion.status == "PUBLISHED",
            ).first()
            if version is None:
                raise RuntimeError("Published template version is unavailable")
            requester = db.query(User).filter(User.id == job.requested_by).first()
            if requester is None:
                raise RuntimeError("Requesting user no longer exists")

            org_context = OrgContext(
                current_org_id=job.org_id,
                allowed_org_ids=[job.org_id],
                selected_org_id=job.org_id,
                is_root=False,
            )
            policy = get_access_policy(requester, org_context, db)
            params = dict(job.render_params or {})
            context = resolve_report_data(
                resolver_key=template.resolver_key,
                entity_id=job.entity_id,
                db=db,
                org_context=org_context,
                user=policy.scoped_user,
                params=params.get("params"),
            )
            snapshot = json.loads(json.dumps(context, default=str))
            payload = {
                "html_content": version.html_content,
                "css_content": version.css_content,
                "header_html": version.header_html,
                "footer_html": version.footer_html,
                "page_size": template.page_size,
                "orientation": template.orientation,
                "context": snapshot,
            }
            pdf_bytes = self.render_pdf(payload, self.timeout_seconds)
            output_key = blob_storage.upload_file(
                file_obj=pdf_bytes,
                folder=f"reports/{job.org_id}",
                original_filename=f"{template.slug}_{job.entity_id}_{job.id}.pdf",
            )

            job.status = "COMPLETED"
            job.output_key = output_key
            job.file_size = len(pdf_bytes)
            job.output_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
            job.data_snapshot = snapshot
            job.is_issued = render_is_issued(template.entity_type, snapshot)
            job.completed_at = _utcnow()
            job.lease_expires_at = None
            job.retry_at = None
            db.commit()
        except Exception as exc:
            db.rollback()
            failed_job = db.query(ReportRenderJob).filter(ReportRenderJob.id == job_id).first()
            if failed_job is None:
                raise
            failed_job.error_message = str(exc)[:4000]
            failed_job.lease_expires_at = None
            if failed_job.attempt_count < failed_job.max_attempts:
                failed_job.status = "PENDING"
                failed_job.retry_at = _utcnow() + timedelta(seconds=2 ** failed_job.attempt_count)
            else:
                failed_job.status = "FAILED"
                failed_job.completed_at = _utcnow()
            db.commit()
            logger.exception("Report render job %s failed", job_id)

    def run_once(self) -> bool:
        with SessionLocal() as db:
            job = self.claim_next(db)
            if job is None:
                return False
            self.process(db, job)
            return True

    def run_forever(self, *, poll_seconds: float = 2.0) -> None:
        while True:
            if not self.run_once():
                time.sleep(poll_seconds)


if __name__ == "__main__":
    ReportRenderWorker().run_forever()

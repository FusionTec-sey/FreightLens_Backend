import hashlib
import json
from datetime import datetime, timezone

from Model.containermgmt.Report.ReportRenderJob import ReportRenderJob
from Utils.blob_storage import blob_storage


ISSUED_PO_STAGES = {
    "PO_ISSUED",
    "PROFORMA",
    "SHIPPED",
    "ARRIVED",
    "RECEIVED",
    "COMPLETED",
}
ISSUED_RFQ_STAGES = {"RFQ_SENT", "QUOTE_RECEIVED", "QUOTE_APPROVED"}


def render_is_issued(entity_type: str | None, snapshot: dict) -> bool:
    stage = str(snapshot.get("lifecycle_stage") or snapshot.get("status") or "").upper()
    if entity_type == "PurchaseOrder":
        return stage in ISSUED_PO_STAGES
    if entity_type == "RFQ":
        return stage in ISSUED_RFQ_STAGES
    return False


def record_completed_render(
    db,
    *,
    template,
    version,
    org_id: int,
    entity_id: int | None,
    params: dict | None,
    requested_by: int,
    pdf_bytes: bytes,
    context: dict,
    is_issued: bool | None = None,
) -> ReportRenderJob:
    """Persist the exact synchronous render bytes and immutable resolver snapshot."""
    snapshot = json.loads(json.dumps(context, default=str))
    issued = render_is_issued(template.entity_type, snapshot) if is_issued is None else is_issued
    job = ReportRenderJob(
        template_id=template.id,
        version_id=version.id,
        org_id=org_id,
        entity_type=template.entity_type,
        entity_id=entity_id,
        render_params={"params": params or {}, "format": "pdf"},
        requested_by=requested_by,
        status="COMPLETED",
        data_snapshot=snapshot,
        file_size=len(pdf_bytes),
        output_sha256=hashlib.sha256(pdf_bytes).hexdigest(),
        is_issued=issued,
        completed_at=datetime.now(timezone.utc),
    )
    db.add(job)
    db.flush()
    job.output_key = blob_storage.upload_file(
        file_obj=pdf_bytes,
        folder=f"reports/{org_id}",
        original_filename=f"{template.slug}_{entity_id}_{job.id}.pdf",
    )
    db.commit()
    db.refresh(job)
    return job

"""Immutable invoice artifacts and auditable print-queue state."""
from sqlalchemy import (
    CheckConstraint, Column, DateTime, DDL, ForeignKey, ForeignKeyConstraint,
    Index, Integer, JSON, String, Text, UniqueConstraint, event, func, text,
)
from sqlalchemy.dialects.postgresql import UUID

from Model.db import Base
from Model.mixins import AuditMixin, OrgMixin
from Model.containermgmt.Inventory.PostingOperation import PostingOperation  # noqa: F401
from Model.containermgmt.Orders.SalesPosting import SalesInvoice  # noqa: F401
from Model.containermgmt.Report.ReportTemplate import ReportTemplate  # noqa: F401
from Model.containermgmt.Report.ReportTemplateVersion import ReportTemplateVersion  # noqa: F401


NONZERO_UUID = "<> '00000000-0000-0000-0000-000000000000'::uuid"
AUDIT_CHECK = "created_by IS NOT NULL AND NOT is_deleted AND deleted_at IS NULL"


class SalesInvoiceArtifact(OrgMixin, AuditMixin, Base):
    """One immutable PDF rendering bound to an exact invoice and template version."""

    __tablename__ = "sales_invoice_artifacts"
    __table_args__ = (
        UniqueConstraint("artifact_key", "org_id", name="uq_sales_invoice_artifact_scope"),
        UniqueConstraint("org_id", "operation_key", name="uq_sales_invoice_artifact_operation"),
        UniqueConstraint(
            "org_id", "invoice_key", "copy_number",
            name="uq_sales_invoice_artifact_copy_number",
        ),
        ForeignKeyConstraint(
            ["invoice_key", "org_id"],
            ["containermgmt.sales_invoices.invoice_key", "containermgmt.sales_invoices.org_id"],
            name="fk_sales_invoice_artifact_invoice",
        ),
        ForeignKeyConstraint(
            ["source_artifact_key", "org_id"],
            ["containermgmt.sales_invoice_artifacts.artifact_key", "containermgmt.sales_invoice_artifacts.org_id"],
            name="fk_sales_invoice_artifact_source",
        ),
        ForeignKeyConstraint(
            ["org_id", "operation_key"],
            ["containermgmt.inventory_posting_operations.org_id", "containermgmt.inventory_posting_operations.operation_key"],
            name="fk_sales_invoice_artifact_operation",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(
            f"artifact_key {NONZERO_UUID} AND operation_key {NONZERO_UUID} "
            "AND artifact_kind IN ('ORIGINAL','COPY') AND copy_number >= 0 "
            "AND ((artifact_kind='ORIGINAL' AND copy_number=0 AND source_artifact_key IS NULL) "
            "OR (artifact_kind='COPY' AND copy_number>0 AND source_artifact_key IS NOT NULL))",
            name="ck_sales_invoice_artifact_identity",
        ),
        CheckConstraint(
            "snapshot_sha256 ~ '^[0-9a-f]{64}$' AND html_sha256 ~ '^[0-9a-f]{64}$' "
            "AND pdf_sha256 ~ '^[0-9a-f]{64}$' AND file_size > 0 "
            "AND length(trim(object_key)) > 0 AND json_typeof(data_snapshot)='object' "
            "AND json_typeof(storage_fingerprint)='object' "
            "AND storage_fingerprint->>'policy'='blob-sha256-v1' "
            "AND length(trim(storage_fingerprint->>'bucket')) > 0 "
            "AND storage_fingerprint->>'object_key'=object_key "
            "AND length(trim(storage_fingerprint->>'version_id')) > 0 "
            "AND (storage_fingerprint->>'size')::integer=file_size "
            "AND storage_fingerprint->>'sha256'=pdf_sha256",
            name="ck_sales_invoice_artifact_content",
        ),
        CheckConstraint(AUDIT_CHECK, name="ck_sales_invoice_artifact_audit"),
        Index(
            "uq_sales_invoice_original_artifact", "org_id", "invoice_key",
            unique=True, postgresql_where=text("artifact_kind='ORIGINAL'"),
        ),
        Index("ix_sales_invoice_artifact_invoice", "org_id", "invoice_key", "copy_number"),
        {"schema": "containermgmt"},
    )
    artifact_key = Column(UUID(as_uuid=True), primary_key=True)
    operation_key = Column(UUID(as_uuid=True), nullable=False)
    invoice_key = Column(UUID(as_uuid=True), nullable=False)
    template_id = Column(Integer, ForeignKey("containermgmt.report_templates.id"), nullable=False)
    template_version_id = Column(
        Integer, ForeignKey("containermgmt.report_template_versions.id"), nullable=False
    )
    artifact_kind = Column(String(12), nullable=False)
    copy_number = Column(Integer, nullable=False)
    source_artifact_key = Column(UUID(as_uuid=True), nullable=True)
    data_snapshot = Column(JSON, nullable=False)
    snapshot_sha256 = Column(String(64), nullable=False)
    html_sha256 = Column(String(64), nullable=False)
    pdf_sha256 = Column(String(64), nullable=False)
    object_key = Column(String(500), nullable=False)
    file_size = Column(Integer, nullable=False)
    storage_fingerprint = Column(JSON, nullable=False)


class SalesInvoicePrintJob(OrgMixin, AuditMixin, Base):
    """Current operational state; immutable events preserve every transition."""

    __tablename__ = "sales_invoice_print_jobs"
    __table_args__ = (
        UniqueConstraint("job_key", "org_id", name="uq_sales_invoice_print_job_scope"),
        UniqueConstraint("org_id", "operation_key", name="uq_sales_invoice_print_job_operation"),
        ForeignKeyConstraint(
            ["artifact_key", "org_id"],
            ["containermgmt.sales_invoice_artifacts.artifact_key", "containermgmt.sales_invoice_artifacts.org_id"],
            name="fk_sales_invoice_print_job_artifact",
        ),
        ForeignKeyConstraint(
            ["org_id", "operation_key"],
            ["containermgmt.inventory_posting_operations.org_id", "containermgmt.inventory_posting_operations.operation_key"],
            name="fk_sales_invoice_print_job_operation",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(
            f"job_key {NONZERO_UUID} AND operation_key {NONZERO_UUID} AND version > 0 "
            "AND status IN ('READY','UNCERTAIN','PRINTED','FAILED') "
            "AND ((status='READY' AND handed_off_at IS NULL AND resolved_at IS NULL "
            "AND resolved_by IS NULL AND failure_code IS NULL AND resolution_note IS NULL) "
            "OR (status='UNCERTAIN' AND handed_off_at IS NOT NULL AND resolved_at IS NULL "
            "AND resolved_by IS NULL AND failure_code IS NULL AND resolution_note IS NULL) "
            "OR (status='PRINTED' AND handed_off_at IS NOT NULL AND resolved_at IS NOT NULL "
            "AND resolved_by IS NOT NULL AND failure_code IS NULL AND resolution_note IS NOT NULL) "
            "OR (status='FAILED' AND resolved_at IS NOT NULL AND resolved_by IS NOT NULL "
            "AND failure_code IS NOT NULL AND resolution_note IS NOT NULL))",
            name="ck_sales_invoice_print_job_identity",
        ),
        CheckConstraint(AUDIT_CHECK, name="ck_sales_invoice_print_job_audit"),
        Index("ix_sales_invoice_print_job_artifact", "org_id", "artifact_key"),
        Index("ix_sales_invoice_print_job_status", "org_id", "status", "created_at"),
        {"schema": "containermgmt"},
    )
    job_key = Column(UUID(as_uuid=True), primary_key=True)
    operation_key = Column(UUID(as_uuid=True), nullable=False)
    artifact_key = Column(UUID(as_uuid=True), nullable=False)
    status = Column(String(12), nullable=False)
    version = Column(Integer, nullable=False)
    handed_off_at = Column(DateTime(timezone=True), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolved_by = Column(Integer, ForeignKey("usercredentials.users.id"), nullable=True)
    failure_code = Column(String(50), nullable=True)
    resolution_note = Column(Text, nullable=True)


class SalesInvoicePrintEvent(OrgMixin, AuditMixin, Base):
    """Append-only state transition bound to a stable posting operation."""

    __tablename__ = "sales_invoice_print_events"
    __table_args__ = (
        UniqueConstraint("org_id", "job_key", "sequence", name="uq_sales_invoice_print_event_sequence"),
        UniqueConstraint("org_id", "operation_key", name="uq_sales_invoice_print_event_operation"),
        ForeignKeyConstraint(
            ["job_key", "org_id"],
            ["containermgmt.sales_invoice_print_jobs.job_key", "containermgmt.sales_invoice_print_jobs.org_id"],
            name="fk_sales_invoice_print_event_job",
        ),
        ForeignKeyConstraint(
            ["org_id", "operation_key"],
            ["containermgmt.inventory_posting_operations.org_id", "containermgmt.inventory_posting_operations.operation_key"],
            name="fk_sales_invoice_print_event_operation",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(
            f"operation_key {NONZERO_UUID} AND sequence > 0 "
            "AND to_status IN ('READY','UNCERTAIN','PRINTED','FAILED') "
            "AND (from_status IS NULL OR from_status IN ('READY','UNCERTAIN'))",
            name="ck_sales_invoice_print_event_identity",
        ),
        CheckConstraint(AUDIT_CHECK, name="ck_sales_invoice_print_event_audit"),
        Index("ix_sales_invoice_print_event_job", "org_id", "job_key", "sequence"),
        {"schema": "containermgmt"},
    )
    id = Column(Integer, primary_key=True)
    job_key = Column(UUID(as_uuid=True), nullable=False)
    operation_key = Column(UUID(as_uuid=True), nullable=False)
    sequence = Column(Integer, nullable=False)
    from_status = Column(String(12), nullable=True)
    to_status = Column(String(12), nullable=False)
    note = Column(Text, nullable=False)


MODELS = (SalesInvoiceArtifact, SalesInvoicePrintJob, SalesInvoicePrintEvent)

IMMUTABLE_FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.reject_sales_invoice_print_history_change()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
RAISE EXCEPTION 'Sales invoice artifact/event history is immutable'; END; $$"""


def immutable_trigger(table):
    return f"""CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE
ON containermgmt.{table} FOR EACH ROW
EXECUTE FUNCTION containermgmt.reject_sales_invoice_print_history_change()"""


JOB_UPDATE_FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.guard_sales_invoice_print_job_update()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Print jobs cannot be deleted'; END IF;
IF NEW.org_id<>OLD.org_id OR NEW.job_key<>OLD.job_key
 OR NEW.operation_key<>OLD.operation_key OR NEW.artifact_key<>OLD.artifact_key
 OR NEW.created_by<>OLD.created_by OR NEW.version<>OLD.version+1 THEN
 RAISE EXCEPTION 'Print job identity and version are immutable'; END IF;
IF NOT ((OLD.status='READY' AND NEW.status IN ('UNCERTAIN','FAILED'))
 OR (OLD.status='UNCERTAIN' AND NEW.status IN ('PRINTED','FAILED'))) THEN
 RAISE EXCEPTION 'Invalid print job transition'; END IF;
RETURN NEW; END; $$"""
JOB_UPDATE_TRIGGER = """CREATE TRIGGER sales_invoice_print_job_update_guard
BEFORE UPDATE OR DELETE ON containermgmt.sales_invoice_print_jobs
FOR EACH ROW EXECUTE FUNCTION containermgmt.guard_sales_invoice_print_job_update()"""


JOB_EVENT_GUARD_FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.check_sales_invoice_print_event()
RETURNS trigger LANGUAGE plpgsql AS $$ DECLARE job record; latest integer; prior_status text; operation record; BEGIN
SELECT version, status, created_by INTO job FROM containermgmt.sales_invoice_print_jobs
WHERE org_id=NEW.org_id AND job_key=NEW.job_key;
SELECT MAX(sequence) INTO latest FROM containermgmt.sales_invoice_print_events
WHERE org_id=NEW.org_id AND job_key=NEW.job_key;
SELECT to_status INTO prior_status FROM containermgmt.sales_invoice_print_events
WHERE org_id=NEW.org_id AND job_key=NEW.job_key AND sequence=NEW.sequence-1;
SELECT kind, created_by INTO operation FROM containermgmt.inventory_posting_operations
WHERE org_id=NEW.org_id AND operation_key=NEW.operation_key;
IF job IS NULL OR latest<>job.version OR NEW.sequence<>job.version
 OR NEW.to_status<>job.status OR operation IS NULL
 OR operation.kind NOT IN ('sales.invoice.print.request.v1','sales.invoice.print.handoff.v1','sales.invoice.print.resolve.v1')
 OR operation.created_by<>NEW.created_by THEN
 RAISE EXCEPTION 'Print event must match the exact job state and operation'; END IF;
IF (NEW.sequence=1 AND (NEW.from_status IS NOT NULL OR NEW.to_status<>'READY'
    OR operation.kind<>'sales.invoice.print.request.v1'))
 OR (NEW.sequence>1 AND (prior_status IS NULL OR NEW.from_status<>prior_status)) THEN
 RAISE EXCEPTION 'Print event chain is invalid'; END IF;
RETURN NULL; END; $$"""
JOB_EVENT_GUARD_TRIGGER = """CREATE CONSTRAINT TRIGGER sales_invoice_print_event_guard
AFTER INSERT ON containermgmt.sales_invoice_print_events DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION containermgmt.check_sales_invoice_print_event()"""

JOB_STATE_GUARD_FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.check_sales_invoice_print_job_state()
RETURNS trigger LANGUAGE plpgsql AS $$ DECLARE matched integer; BEGIN
IF TG_OP='INSERT' AND (NEW.version<>1 OR NEW.status<>'READY') THEN
 RAISE EXCEPTION 'Print jobs must start READY at version 1'; END IF;
SELECT COUNT(*) INTO matched FROM containermgmt.sales_invoice_print_events
WHERE org_id=NEW.org_id AND job_key=NEW.job_key AND sequence=NEW.version
 AND to_status=NEW.status;
IF matched<>1 THEN RAISE EXCEPTION 'Print job must have one exact current-state event'; END IF;
RETURN NULL; END; $$"""
JOB_STATE_GUARD_TRIGGER = """CREATE CONSTRAINT TRIGGER sales_invoice_print_job_state_guard
AFTER INSERT OR UPDATE ON containermgmt.sales_invoice_print_jobs DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION containermgmt.check_sales_invoice_print_job_state()"""

ARTIFACT_GUARD_FUNCTION = """CREATE OR REPLACE FUNCTION containermgmt.check_sales_invoice_artifact()
RETURNS trigger LANGUAGE plpgsql AS $$ DECLARE source record; version record; operation record; BEGIN
SELECT template_id, status INTO version FROM containermgmt.report_template_versions
WHERE id=NEW.template_version_id;
SELECT kind, created_by INTO operation FROM containermgmt.inventory_posting_operations
WHERE org_id=NEW.org_id AND operation_key=NEW.operation_key;
IF version IS NULL OR version.template_id<>NEW.template_id
 OR operation IS NULL OR operation.kind<>'sales.invoice.print.request.v1'
 OR operation.created_by<>NEW.created_by THEN
 RAISE EXCEPTION 'Invoice artifact must use the exact published template and operation'; END IF;
IF NEW.artifact_kind='COPY' THEN
 SELECT org_id, invoice_key, artifact_kind, copy_number, template_id, template_version_id INTO source
 FROM containermgmt.sales_invoice_artifacts
 WHERE org_id=NEW.org_id AND artifact_key=NEW.source_artifact_key;
 IF source IS NULL OR source.invoice_key<>NEW.invoice_key
    OR source.artifact_kind<>'ORIGINAL' OR source.copy_number<>0
    OR source.template_id<>NEW.template_id OR source.template_version_id<>NEW.template_version_id THEN
  RAISE EXCEPTION 'COPY must reference the exact original for this invoice'; END IF;
ELSIF version.status<>'PUBLISHED' THEN
 RAISE EXCEPTION 'Original invoice artifact requires a published template version';
END IF;
RETURN NULL; END; $$"""
ARTIFACT_GUARD_TRIGGER = """CREATE CONSTRAINT TRIGGER sales_invoice_artifact_guard
AFTER INSERT ON containermgmt.sales_invoice_artifacts DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION containermgmt.check_sales_invoice_artifact()"""


event.listen(SalesInvoiceArtifact.__table__, "after_create", DDL(IMMUTABLE_FUNCTION))
event.listen(SalesInvoiceArtifact.__table__, "after_create", DDL(immutable_trigger("sales_invoice_artifacts")))
event.listen(SalesInvoiceArtifact.__table__, "after_create", DDL(ARTIFACT_GUARD_FUNCTION))
event.listen(SalesInvoiceArtifact.__table__, "after_create", DDL(ARTIFACT_GUARD_TRIGGER))
event.listen(SalesInvoicePrintJob.__table__, "after_create", DDL(JOB_UPDATE_FUNCTION))
event.listen(SalesInvoicePrintJob.__table__, "after_create", DDL(JOB_UPDATE_TRIGGER))
event.listen(SalesInvoicePrintJob.__table__, "after_create", DDL(JOB_STATE_GUARD_FUNCTION))
event.listen(SalesInvoicePrintJob.__table__, "after_create", DDL(JOB_STATE_GUARD_TRIGGER))
event.listen(SalesInvoicePrintEvent.__table__, "after_create", DDL(IMMUTABLE_FUNCTION))
event.listen(SalesInvoicePrintEvent.__table__, "after_create", DDL(immutable_trigger("sales_invoice_print_events")))
event.listen(SalesInvoicePrintEvent.__table__, "after_create", DDL(JOB_EVENT_GUARD_FUNCTION))
event.listen(SalesInvoicePrintEvent.__table__, "after_create", DDL(JOB_EVENT_GUARD_TRIGGER))

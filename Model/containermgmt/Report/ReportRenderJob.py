import uuid
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, JSON, func
from sqlalchemy.orm import relationship
from Model.db import Base

# TABLE: Queue of document/PDF generation jobs, with retry and lease tracking.
class ReportRenderJob(Base):
    __tablename__ = "report_render_jobs"
    __table_args__ = {"schema": "containermgmt"}

    # id - VARCHAR(36), primary key.
    # Unique job id (UUID).
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    # template_id - INTEGER, foreign key -> containermgmt.report_templates.id, required.
    # Template being rendered.
    template_id = Column(Integer, ForeignKey("containermgmt.report_templates.id"), nullable=False, index=True)
    # version_id - INTEGER, foreign key -> containermgmt.report_template_versions.id, optional.
    # Template version used.
    version_id = Column(Integer, ForeignKey("containermgmt.report_template_versions.id"), nullable=True)
    # org_id - INTEGER, foreign key -> usercredentials.organisations.id, required.
    # Company that requested it.
    org_id = Column(Integer, ForeignKey("usercredentials.organisations.id"), nullable=False, index=True)
    # entity_type - VARCHAR(100), optional.
    # Kind of record being printed.
    entity_type = Column(String(100), nullable=True)
    # entity_id - INTEGER, optional.
    # Id of the record being printed.
    entity_id = Column(Integer, nullable=True, index=True)
    # render_params - JSON, optional.
    # Options chosen for this render (JSON).
    render_params = Column(JSON, nullable=True)
    # status - VARCHAR(20), optional, default PENDING.
    # PENDING, RENDERING, COMPLETED or FAILED.
    status = Column(String(20), default="PENDING", index=True)  # PENDING, RENDERING, COMPLETED, FAILED
    # output_key - VARCHAR(500), optional.
    # Storage key of the finished file.
    output_key = Column(String(500), nullable=True)  # RustFS object key
    # file_size - INTEGER, optional.
    # Size of the output in bytes.
    file_size = Column(Integer, nullable=True)
    # error_message - TEXT, optional.
    # Why it failed.
    error_message = Column(Text, nullable=True)
    # data_snapshot - JSON, optional.
    # Data used for the render (JSON), so reprints match.
    data_snapshot = Column(JSON, nullable=True)
    # output_sha256 - VARCHAR(64), optional.
    # Checksum of the output, to detect tampering.
    output_sha256 = Column(String(64), nullable=True)
    # attempt_count - INTEGER, required, default 0.
    # Attempts made so far.
    attempt_count = Column(Integer, nullable=False, default=0)
    # max_attempts - INTEGER, required, default 3.
    # Attempts allowed before giving up.
    max_attempts = Column(Integer, nullable=False, default=3)
    # worker_id - VARCHAR(100), optional.
    # Worker process handling the job.
    worker_id = Column(String(100), nullable=True, index=True)
    # started_at - TIMESTAMP WITH TIME ZONE, optional.
    # When rendering started.
    started_at = Column(DateTime(timezone=True), nullable=True)
    # heartbeat_at - TIMESTAMP WITH TIME ZONE, optional.
    # Last sign of life from the worker.
    heartbeat_at = Column(DateTime(timezone=True), nullable=True)
    # lease_expires_at - TIMESTAMP WITH TIME ZONE, optional.
    # When another worker may take the job over.
    lease_expires_at = Column(DateTime(timezone=True), nullable=True, index=True)
    # retry_at - TIMESTAMP WITH TIME ZONE, optional.
    # When to try again after a failure.
    retry_at = Column(DateTime(timezone=True), nullable=True, index=True)
    # requested_at - TIMESTAMP WITH TIME ZONE, required.
    # When the job was requested.
    requested_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # completed_at - TIMESTAMP WITH TIME ZONE, optional.
    # When it finished.
    completed_at = Column(DateTime(timezone=True), nullable=True)
    # requested_by - INTEGER, foreign key -> usercredentials.users.id, required.
    # User who requested it.
    requested_by = Column(Integer, ForeignKey("usercredentials.users.id"), nullable=False)

    # Relationships
    template = relationship("ReportTemplate", back_populates="render_jobs")
    requester = relationship("User", foreign_keys=[requested_by], viewonly=True)

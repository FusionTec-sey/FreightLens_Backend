import uuid
from sqlalchemy import Boolean, Column, Integer, String, Text, DateTime, ForeignKey, JSON, func
from sqlalchemy.orm import relationship
from Model.db import Base

class ReportRenderJob(Base):
    __tablename__ = "report_render_jobs"
    __table_args__ = {"schema": "containermgmt"}

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    template_id = Column(Integer, ForeignKey("containermgmt.report_templates.id"), nullable=False, index=True)
    version_id = Column(Integer, ForeignKey("containermgmt.report_template_versions.id"), nullable=True)
    org_id = Column(Integer, ForeignKey("usercredentials.organisations.id"), nullable=False, index=True)
    entity_type = Column(String(100), nullable=True)
    entity_id = Column(Integer, nullable=True, index=True)
    render_params = Column(JSON, nullable=True)
    status = Column(String(20), default="PENDING", index=True)  # PENDING, RENDERING, COMPLETED, FAILED
    output_key = Column(String(500), nullable=True)  # RustFS object key
    file_size = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    data_snapshot = Column(JSON, nullable=True)
    output_sha256 = Column(String(64), nullable=True)
    is_issued = Column(Boolean, nullable=False, default=False, server_default="false", index=True)
    retain_until = Column(DateTime(timezone=True), nullable=True, index=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    worker_id = Column(String(100), nullable=True, index=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    heartbeat_at = Column(DateTime(timezone=True), nullable=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True, index=True)
    retry_at = Column(DateTime(timezone=True), nullable=True, index=True)
    requested_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    requested_by = Column(Integer, ForeignKey("usercredentials.users.id"), nullable=False)

    # Relationships
    template = relationship("ReportTemplate", back_populates="render_jobs")
    requester = relationship("User", foreign_keys=[requested_by], viewonly=True)

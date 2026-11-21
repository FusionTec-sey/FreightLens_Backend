from sqlalchemy import Boolean, Column, ForeignKey, Integer, JSON, String, text, UniqueConstraint
from sqlalchemy.orm import relationship

from Model.db import Base
from Model.mixins import AuditMixin, OrgMixin


# TABLE: Which template a company uses for a document type.
class ReportTemplateAssignment(OrgMixin, AuditMixin, Base):
    __tablename__ = "report_template_assignments"
    __table_args__ = (
        UniqueConstraint("org_id", "template_id", name="uq_report_template_assignment"),
        {"schema": "containermgmt"},
    )

    # id - INTEGER, primary key.
    # Unique row number.
    id = Column(Integer, primary_key=True, autoincrement=True)
    # template_id - INTEGER, foreign key -> containermgmt.report_templates.id, required.
    # Template assigned.
    template_id = Column(
        Integer,
        ForeignKey("containermgmt.report_templates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # entity_type - VARCHAR(100), required.
    # Document type it is assigned to.
    entity_type = Column(String(100), nullable=False, index=True)
    # is_active - BOOLEAN, required, default True.
    # False hides the record from use without deleting it.
    is_active = Column(Boolean, nullable=False, default=True)
    # is_default - BOOLEAN, required, default False.
    # True = default choice for that document type.
    is_default = Column(Boolean, nullable=False, default=False)
    # default_options - JSON, required.
    # Default render options (JSON).
    default_options = Column(JSON, nullable=False, default=dict, server_default=text("'{}'::json"))

    template = relationship("ReportTemplate", back_populates="assignments")

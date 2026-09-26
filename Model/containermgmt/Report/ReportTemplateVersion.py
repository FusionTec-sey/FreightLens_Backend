from sqlalchemy import Column, Integer, String, Text, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from Model.db import Base
from Model.mixins import AuditMixin

class ReportTemplateVersion(AuditMixin, Base):
    __tablename__ = "report_template_versions"
    __table_args__ = (
        UniqueConstraint("template_id", "version_number", name="uq_template_version"),
        {"schema": "containermgmt"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    template_id = Column(
        Integer,
        ForeignKey("containermgmt.report_templates.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    version_number = Column(Integer, nullable=False, default=1)
    status = Column(String(20), default="DRAFT", index=True)  # DRAFT, PUBLISHED, ARCHIVED
    html_content = Column(Text, nullable=False)
    css_content = Column(Text, nullable=True)
    header_html = Column(Text, nullable=True)
    footer_html = Column(Text, nullable=True)
    change_notes = Column(Text, nullable=True)

    # Relationships
    template = relationship("ReportTemplate", back_populates="versions")

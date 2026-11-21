from sqlalchemy import Column, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from Model.db import Base
from Model.mixins import AuditMixin

# TABLE: One saved version of a report template.
class ReportTemplateVersion(AuditMixin, Base):
    __tablename__ = "report_template_versions"
    __table_args__ = (
        UniqueConstraint("template_id", "version_number", name="uq_template_version"),
        {"schema": "containermgmt"},
    )

    # id - INTEGER, primary key.
    # Unique row number.
    id = Column(Integer, primary_key=True, autoincrement=True)
    # template_id - INTEGER, foreign key -> containermgmt.report_templates.id, required.
    # Template this version belongs to.
    template_id = Column(
        Integer,
        ForeignKey("containermgmt.report_templates.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    # version_number - INTEGER, required, default 1.
    # Version number, 1, 2, 3...
    version_number = Column(Integer, nullable=False, default=1)
    # status - VARCHAR(20), optional, default DRAFT.
    # DRAFT, PUBLISHED or ARCHIVED.
    status = Column(String(20), default="DRAFT", index=True)  # DRAFT, PUBLISHED, ARCHIVED
    # html_content - TEXT, required.
    # HTML body of the layout.
    html_content = Column(Text, nullable=False)
    # css_content - TEXT, optional.
    # Styling.
    css_content = Column(Text, nullable=True)
    # header_html - TEXT, optional.
    # Page header HTML.
    header_html = Column(Text, nullable=True)
    # footer_html - TEXT, optional.
    # Page footer HTML.
    footer_html = Column(Text, nullable=True)
    # paper_settings - JSON, optional.
    # Margins/paper options (JSON).
    paper_settings = Column(JSON, nullable=True)
    # options_schema - JSON, optional.
    # Options users can choose when printing (JSON).
    options_schema = Column(JSON, nullable=True)
    # change_notes - TEXT, optional.
    # What changed in this version.
    change_notes = Column(Text, nullable=True)

    # Relationships
    template = relationship("ReportTemplate", back_populates="versions")

    @property
    def changelog(self):
        return self.change_notes

    @changelog.setter
    def changelog(self, value):
        self.change_notes = value


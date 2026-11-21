from sqlalchemy import Column, Integer, String, Text, Boolean, JSON, UniqueConstraint, desc, ARRAY
from sqlalchemy.orm import relationship
from Model.db import Base
from Model.mixins import OrgMixin, AuditMixin

# TABLE: A report/document layout (PO PDF, container list...).
class ReportTemplate(OrgMixin, AuditMixin, Base):
    __tablename__ = "report_templates"
    __table_args__ = (
        UniqueConstraint("org_id", "slug", name="uq_report_templates_org_slug"),
        {"schema": "containermgmt"},
    )

    # id - INTEGER, primary key.
    # Unique row number.
    id = Column(Integer, primary_key=True, autoincrement=True)
    # slug - VARCHAR(100), required.
    # URL-safe identifier, unique per company.
    slug = Column(String(100), nullable=False, index=True)
    # name - VARCHAR(255), required.
    # Template name.
    name = Column(String(255), nullable=False)
    # description - TEXT, optional.
    # Free-text description.
    description = Column(Text, nullable=True)
    # category - VARCHAR(50), required.
    # LOGISTICS, ORDERS or CROSS_MODULE.
    category = Column(String(50), nullable=False, index=True)  # LOGISTICS, ORDERS, CROSS_MODULE
    # resolver_key - VARCHAR(100), required.
    # Code that supplies the data for this template.
    resolver_key = Column(String(100), nullable=False, index=True)  # maps to DataResolverRegistry
    # entity_type - VARCHAR(100), required.
    # Kind of record it prints (PurchaseOrder, ContainerDetails...).
    entity_type = Column(String(100), nullable=False)  # PurchaseOrder, ContainerDetails, etc.
    # is_system - BOOLEAN, required, default False.
    # True = built-in template.
    is_system = Column(Boolean, default=False, nullable=False)
    # is_active - BOOLEAN, required, default True.
    # False hides the record from use without deleting it.
    is_active = Column(Boolean, default=True, nullable=False)
    # active_org_ids - INTEGER[], optional.
    # Companies the template is enabled for.
    active_org_ids = Column(ARRAY(Integer), default=list, nullable=True)
    # template_type - VARCHAR(30), required, default DOCUMENT.
    # DOCUMENT or OPERATIONAL_TABULAR.
    template_type = Column(
        String(30), default="DOCUMENT", server_default="DOCUMENT", nullable=False
    )  # "DOCUMENT" or "OPERATIONAL_TABULAR"
    # table_config - JSON, optional.
    # Column setup for tabular reports (JSON).
    table_config = Column(JSON, nullable=True)
    # paper_settings - JSON, optional.
    # Margins/paper options (JSON).
    paper_settings = Column(JSON, nullable=True)
    # page_size - VARCHAR(20), optional, default A4.
    # Paper size, e.g. A4.
    page_size = Column(String(20), default="A4")
    # orientation - VARCHAR(20), optional, default portrait.
    # portrait or landscape.
    orientation = Column(String(20), default="portrait")
    # output_format - VARCHAR(10), optional, default pdf.
    # pdf, etc.
    output_format = Column(String(10), default="pdf")
    # active_version_id - INTEGER, optional.
    # Version currently in use.
    active_version_id = Column(Integer, nullable=True)
    # default_params - JSON, optional.
    # Default options (JSON).
    default_params = Column(JSON, nullable=True)

    # Relationships
    versions = relationship(
        "ReportTemplateVersion",
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="desc(ReportTemplateVersion.version_number)"
    )
    render_jobs = relationship("ReportRenderJob", back_populates="template")
    assignments = relationship(
        "ReportTemplateAssignment",
        back_populates="template",
        cascade="all, delete-orphan",
    )

    @property
    def active_version_number(self):
        if self.versions:
            for v in self.versions:
                if v.id == self.active_version_id:
                    return v.version_number
        return None


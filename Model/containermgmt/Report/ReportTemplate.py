from sqlalchemy import Column, Integer, String, Text, Boolean, JSON, UniqueConstraint, desc
from sqlalchemy.orm import relationship
from Model.db import Base
from Model.mixins import OrgMixin, AuditMixin

class ReportTemplate(OrgMixin, AuditMixin, Base):
    __tablename__ = "report_templates"
    __table_args__ = (
        UniqueConstraint("org_id", "slug", name="uq_report_templates_org_slug"),
        {"schema": "containermgmt"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    slug = Column(String(100), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(50), nullable=False, index=True)  # LOGISTICS, ORDERS, CROSS_MODULE
    resolver_key = Column(String(100), nullable=False, index=True)  # maps to DataResolverRegistry
    entity_type = Column(String(100), nullable=False)  # PurchaseOrder, ContainerDetails, etc.
    is_system = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    page_size = Column(String(20), default="A4")
    orientation = Column(String(20), default="portrait")
    output_format = Column(String(10), default="pdf")
    active_version_id = Column(Integer, nullable=True)
    default_params = Column(JSON, nullable=True)

    # Relationships
    versions = relationship(
        "ReportTemplateVersion",
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="desc(ReportTemplateVersion.version_number)"
    )
    render_jobs = relationship("ReportRenderJob", back_populates="template")

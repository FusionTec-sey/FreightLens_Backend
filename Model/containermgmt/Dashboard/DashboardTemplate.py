from sqlalchemy import Boolean, Column, ForeignKey, Integer, JSON, String, Text, text
from sqlalchemy.orm import relationship

from Model.db import Base
from Model.mixins import AuditMixin, OrgMixin


class DashboardTemplate(OrgMixin, AuditMixin, Base):
    __tablename__ = "dashboard_templates"
    __table_args__ = {"schema": "containermgmt"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    role_id = Column(Integer, ForeignKey("usercredentials.roles.id"), nullable=False, index=True)
    description = Column(Text, nullable=True)
    is_default = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    widgets = Column(JSON, nullable=False, default=list, server_default=text("'[]'::json"))

    role = relationship("Role", viewonly=True)

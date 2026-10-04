from sqlalchemy import Column, ForeignKey, Integer, JSON, String, UniqueConstraint, text
from sqlalchemy.orm import relationship

from Model.db import Base
from Model.mixins import AuditMixin, OrgMixin


class UserDashboardConfig(OrgMixin, AuditMixin, Base):
    __tablename__ = "user_dashboard_configs"
    __table_args__ = (
        UniqueConstraint("user_id", "org_id", name="uq_user_dashboard_config_user_org"),
        {"schema": "usercredentials"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("usercredentials.users.id"), nullable=False, index=True)
    template_id = Column(
        Integer,
        ForeignKey("containermgmt.dashboard_templates.id", ondelete="SET NULL"),
        nullable=True,
    )
    widgets = Column(JSON, nullable=False, default=list, server_default=text("'[]'::json"))
    layout_mode = Column(String(50), nullable=False, default="grid", server_default="grid")

    template = relationship("DashboardTemplate", viewonly=True)

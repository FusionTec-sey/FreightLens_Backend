from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, text
from sqlalchemy.orm import relationship
from .user_roles import user_roles
from .role_permissions import role_permissions
from ..db import Base
from ..mixins import AuditMixin

class Role(AuditMixin, Base):
    __tablename__ = 'roles'
    __table_args__ = {'schema': 'usercredentials'}
    id = Column(Integer, primary_key=True)
    name = Column(String(45), nullable=False)
    org_id = Column(Integer, ForeignKey('usercredentials.organisations.id'), nullable=True, index=True)
    is_platform_admin = Column(Boolean, default=False, server_default=text('false'), nullable=False)

    users = relationship("User", secondary=user_roles, back_populates="roles")
    permissions = relationship("Permission", secondary=role_permissions, back_populates="roles")

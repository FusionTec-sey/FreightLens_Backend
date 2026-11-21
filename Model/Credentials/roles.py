from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, text
from sqlalchemy.orm import relationship
from .user_roles import user_roles
from .role_permissions import role_permissions
from ..db import Base
from ..mixins import AuditMixin

# TABLE: Named job roles (e.g. Accounts, Stores) that carry permissions.
class Role(AuditMixin, Base):
    __tablename__ = 'roles'
    __table_args__ = {'schema': 'usercredentials'}
    # id - INTEGER, primary key.
    # Unique row number.
    id = Column(Integer, primary_key=True)
    # name - VARCHAR(45), required.
    # Role name.
    name = Column(String(45), nullable=False)
    # org_id - INTEGER, foreign key -> usercredentials.organisations.id, optional.
    # Company that owns the role (NULL = available to every company).
    org_id = Column(Integer, ForeignKey('usercredentials.organisations.id'), nullable=True, index=True)
    # is_platform_admin - BOOLEAN, required, default false.
    # True = super-admin role across the whole platform.
    is_platform_admin = Column(Boolean, default=False, server_default=text('false'), nullable=False)

    users = relationship("User", secondary=user_roles, back_populates="roles")
    permissions = relationship("Permission", secondary=role_permissions, back_populates="roles")

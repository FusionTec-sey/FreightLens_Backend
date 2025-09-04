from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship
from .user_roles import user_roles
from .role_permissions import role_permissions
from ..db import Base

class Role(Base):
    __tablename__ = 'roles'
    __table_args__ = {'schema': 'usercredentials'}
    id = Column(Integer, primary_key=True)
    name = Column(String(45), unique=True, nullable=False)

    users = relationship("User", secondary=user_roles, back_populates="roles")
    permissions = relationship("Permission", secondary=role_permissions, back_populates="roles")

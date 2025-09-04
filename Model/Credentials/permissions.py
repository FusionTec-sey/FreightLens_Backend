from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship
from .role_permissions import role_permissions
from ..db import Base

class Permission(Base):
    __tablename__ = 'permissions'
    __table_args__ = {'schema': 'usercredentials'}
    id = Column(Integer, primary_key=True)
    name = Column(String(45), unique=True, nullable=False)
    description = Column(String(45))

    roles = relationship("Role", secondary=role_permissions, back_populates="permissions")

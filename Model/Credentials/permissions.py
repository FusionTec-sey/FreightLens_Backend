from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship
from .role_permissions import role_permissions
from ..db import Base

# TABLE: Individual rights (e.g. Approve_Variance) that roles can be granted.
class Permission(Base):
    __tablename__ = 'permissions'
    __table_args__ = {'schema': 'usercredentials'}
    # id - INTEGER, primary key.
    # Unique row number.
    id = Column(Integer, primary_key=True)
    # name - VARCHAR(45), required, unique.
    # Unique permission code checked by the API.
    name = Column(String(45), unique=True, nullable=False)
    # description - VARCHAR(255), optional.
    # What the permission allows.
    description = Column(String(255))

    roles = relationship("Role", secondary=role_permissions, back_populates="permissions")

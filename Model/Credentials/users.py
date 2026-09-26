from sqlalchemy import Column, Integer, String, ForeignKey, ARRAY
from sqlalchemy.orm import relationship
from .user_roles import user_roles
from ..db import Base
from ..mixins import AuditMixin

class User(AuditMixin, Base):
    __tablename__ = 'users'
    __table_args__ = {'schema': 'usercredentials'}
    id = Column(Integer, primary_key=True)
    username = Column(String(45), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    org_id = Column(Integer, ForeignKey('usercredentials.organisations.id'), nullable=True, default=1)
    allowed_org_ids = Column(ARRAY(Integer), nullable=True)

    organisation = relationship("Organisation", back_populates="users")
    roles = relationship("Role", secondary=user_roles, back_populates="users")
    refresh_tokens = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")


from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, func, ARRAY
from sqlalchemy.orm import relationship
from ..db import Base

class Organisation(Base):
    __tablename__ = 'organisations'
    __table_args__ = {'schema': 'usercredentials'}

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False)
    code = Column(String(20), nullable=True)
    display_name = Column(String(150), nullable=True)
    parent_org_id = Column(Integer, ForeignKey('usercredentials.organisations.id'), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    logo_url = Column(String(500), nullable=True)
    modules = Column(ARRAY(String), nullable=False, default=lambda: ["LOGISTICS", "ORDERS"], server_default="{LOGISTICS,ORDERS}")
    plan = Column(String(50), default="complete", nullable=True)
    base_currency = Column(String(10), default="SCR", nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Self-referential hierarchy
    parent = relationship("Organisation", remote_side=[id], back_populates="children")
    children = relationship("Organisation", back_populates="parent")
    users = relationship("User", back_populates="organisation")

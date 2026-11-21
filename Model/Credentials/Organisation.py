from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, func, ARRAY
from sqlalchemy.orm import relationship
from ..db import Base

# TABLE: Companies (tenants) using the system. Almost every business row is tied to one through
#        org_id.
class Organisation(Base):
    __tablename__ = 'organisations'
    __table_args__ = {'schema': 'usercredentials'}

    # id - INTEGER, primary key.
    # Unique row number.
    id = Column(Integer, primary_key=True, autoincrement=True)
    # name - VARCHAR(100), required, unique.
    # Unique internal company name.
    name = Column(String(100), unique=True, nullable=False)
    # code - VARCHAR(20), optional.
    # Short company code.
    code = Column(String(20), nullable=True)
    # display_name - VARCHAR(150), optional.
    # Name shown on screens and printed documents.
    display_name = Column(String(150), nullable=True)
    # parent_org_id - INTEGER, foreign key -> usercredentials.organisations.id, optional.
    # Parent company, for group hierarchies (self-reference).
    parent_org_id = Column(Integer, ForeignKey('usercredentials.organisations.id'), nullable=True)
    # is_active - BOOLEAN, required, default True.
    # False = company disabled; its users cannot work.
    is_active = Column(Boolean, default=True, nullable=False)
    # logo_url - VARCHAR(500), optional.
    # Location of the company logo image.
    logo_url = Column(String(500), nullable=True)
    # modules - TEXT[], required, default {LOGISTICS,ORDERS}.
    # Modules switched on for this company, e.g. LOGISTICS, ORDERS.
    modules = Column(ARRAY(String), nullable=False, default=lambda: ["LOGISTICS", "ORDERS"], server_default="{LOGISTICS,ORDERS}")
    # plan - VARCHAR(50), optional, default complete.
    # Subscription plan tier.
    plan = Column(String(50), default="complete", nullable=True)
    # base_currency - VARCHAR(10), required, default SCR.
    # Company reporting currency (default SCR); *_base amounts convert into it.
    base_currency = Column(String(10), default="SCR", nullable=False)
    # created_at - TIMESTAMP WITH TIME ZONE, required.
    # When the row was created.
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # updated_at - TIMESTAMP WITH TIME ZONE, required.
    # When the row was last changed.
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Self-referential hierarchy
    parent = relationship("Organisation", remote_side=[id], back_populates="children")
    children = relationship("Organisation", back_populates="parent")
    users = relationship("User", back_populates="organisation")

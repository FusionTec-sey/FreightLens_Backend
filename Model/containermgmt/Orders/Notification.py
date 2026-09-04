from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from ...db import Base
from ...mixins import OrgMixin

class Notification(OrgMixin, Base):
    __tablename__ = "notifications"
    __table_args__ = {'schema': 'containermgmt'}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("usercredentials.users.id"), nullable=True, index=True)
    
    # Event Types: REQUEST_SUBMITTED, REQUEST_RETURNED, PO_ORDERED, PAYMENT_RECORDED,
    # PACKED, SHIPPED, CARRIER_ARRIVED, GOODS_RECEIVED, DEFECT_REPORTED, DEFECT_RESOLVED
    event_type = Column(String(50), nullable=False, index=True)
    
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    
    # Link reference for clicking in UI
    link_entity_type = Column(String(50), nullable=True)  # REQUEST, PO, RECEIPT, DEFECT, CONTAINER
    link_entity_id = Column(Integer, nullable=True)
    
    is_read = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    user = relationship("User", foreign_keys=[user_id], viewonly=True)

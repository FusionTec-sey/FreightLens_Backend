from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from ...db import Base
from ...mixins import OrgMixin

# TABLE: In-app alerts shown to users.
class Notification(OrgMixin, Base):
    __tablename__ = "notifications"
    __table_args__ = {'schema': 'containermgmt'}

    # id - INTEGER, primary key.
    # Unique row number.
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    # user_id - INTEGER, foreign key -> usercredentials.users.id, optional.
    # User who receives the alert.
    user_id = Column(Integer, ForeignKey("usercredentials.users.id"), nullable=True, index=True)
    
    # Event Types: REQUEST_SUBMITTED, REQUEST_RETURNED, PO_ORDERED, PAYMENT_RECORDED,
    # PACKED, SHIPPED, CARRIER_ARRIVED, GOODS_RECEIVED, DEFECT_REPORTED, DEFECT_RESOLVED
    # event_type - VARCHAR(50), required.
    # What happened: REQUEST_SUBMITTED, PO_ORDERED, PAYMENT_RECORDED, GOODS_RECEIVED, DEFECT_REPORTED...
    event_type = Column(String(50), nullable=False, index=True)
    
    # title - VARCHAR(255), required.
    # Alert headline.
    title = Column(String(255), nullable=False)
    # message - TEXT, required.
    # Alert text.
    message = Column(Text, nullable=False)
    
    # Link reference for clicking in UI
    # link_entity_type - VARCHAR(50), optional.
    # Kind of record to open when clicked (REQUEST, PO, RECEIPT, DEFECT, CONTAINER).
    link_entity_type = Column(String(50), nullable=True)  # REQUEST, PO, RECEIPT, DEFECT, CONTAINER
    # link_entity_id - INTEGER, optional.
    # Id of the record to open when clicked.
    link_entity_id = Column(Integer, nullable=True)
    
    # is_read - BOOLEAN, optional, default False.
    # True once the user has seen it.
    is_read = Column(Boolean, default=False, index=True)
    # created_at - TIMESTAMP WITH TIME ZONE, required.
    # When the row was created.
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    user = relationship("User", foreign_keys=[user_id], viewonly=True)

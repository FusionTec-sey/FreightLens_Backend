from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from ...db import Base
from ...mixins import OrgMixin

class OrderStatusHistory(OrgMixin, Base):
    __tablename__ = "order_status_history"
    __table_args__ = {'schema': 'containermgmt'}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    
    # Entity reference
    entity_type = Column(String(50), nullable=False, default="PO")  # REQUEST, PO, RECEIPT, DEFECT
    entity_id = Column(Integer, nullable=False, index=True)
    
    po_id = Column(Integer, ForeignKey("containermgmt.purchase_orders.id", ondelete="CASCADE"), nullable=True, index=True)
    
    from_status = Column(String(50), nullable=True)
    to_status = Column(String(50), nullable=False)
    to_status_label = Column(String(100), nullable=True)
    
    changed_by = Column(Integer, ForeignKey("usercredentials.users.id"), nullable=True)
    changed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    notes = Column(Text, nullable=True)

    # Relationships
    purchase_order = relationship("PurchaseOrder", back_populates="status_history")
    user = relationship("User", foreign_keys=[changed_by], viewonly=True)

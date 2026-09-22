from sqlalchemy import Column, Integer, String, Text, ForeignKey, Numeric
from sqlalchemy.orm import relationship
from ...db import Base
from ...mixins import AuditMixin

class POItemHistory(AuditMixin, Base):
    """
    Immutable audit delta log for changes made to line items across all lifecycle stages.
    """
    __tablename__ = "po_item_history"
    __table_args__ = {'schema': 'containermgmt'}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    po_item_id = Column(Integer, ForeignKey("containermgmt.po_items.id", ondelete="CASCADE"), nullable=False, index=True)
    po_id = Column(Integer, ForeignKey("containermgmt.purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    
    lifecycle_stage = Column(String(30), nullable=False) # Stage when change occurred
    lifecycle_version = Column(Integer, nullable=False)  # Version snapshot number
    action = Column(String(20), nullable=False)          # CREATE, UPDATE, REMOVE, SUBSTITUTE, RESTORE
    
    # Delta tracking
    field_name = Column(String(50), nullable=True)       # e.g., 'unit_price', 'quantity_ordered', 'ALL'
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    
    # Snapshot of key fields at time of change
    quantity = Column(Numeric(12, 2), nullable=True)
    unit_price = Column(Numeric(14, 2), nullable=True)
    total_price = Column(Numeric(14, 2), nullable=True)
    
    reason = Column(Text, nullable=True)                 # Mandatory for CRITICAL level changes

    # Relationships
    po_item = relationship("POItem", back_populates="history")
    purchase_order = relationship("PurchaseOrder", foreign_keys=[po_id])

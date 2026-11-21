from sqlalchemy import Column, Integer, String, Text, ForeignKey, Numeric
from sqlalchemy.orm import relationship
from ...db import Base
from ...mixins import AuditMixin

# TABLE: Change log for PO lines across all lifecycle stages.
class POItemHistory(AuditMixin, Base):
    """
    Immutable audit delta log for changes made to line items across all lifecycle stages.
    """
    __tablename__ = "po_item_history"
    __table_args__ = {'schema': 'containermgmt'}

    # id - INTEGER, primary key.
    # Unique row number.
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    # po_item_id - INTEGER, foreign key -> containermgmt.po_items.id, required.
    # PO line that changed.
    po_item_id = Column(Integer, ForeignKey("containermgmt.po_items.id", ondelete="CASCADE"), nullable=False, index=True)
    # po_id - INTEGER, foreign key -> containermgmt.purchase_orders.id, required.
    # Purchase order (or RFQ) this row belongs to.
    po_id = Column(Integer, ForeignKey("containermgmt.purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # lifecycle_stage - VARCHAR(30), required.
    # Stage when the change happened.
    lifecycle_stage = Column(String(30), nullable=False) # Stage when change occurred
    # lifecycle_version - INTEGER, required.
    # Version number at the time.
    lifecycle_version = Column(Integer, nullable=False)  # Version snapshot number
    # action - VARCHAR(20), required.
    # CREATE, UPDATE, REMOVE, SUBSTITUTE or RESTORE.
    action = Column(String(20), nullable=False)          # CREATE, UPDATE, REMOVE, SUBSTITUTE, RESTORE
    
    # Delta tracking
    # field_name - VARCHAR(50), optional.
    # Field changed, e.g. unit_price (ALL for whole line).
    field_name = Column(String(50), nullable=True)       # e.g., 'unit_price', 'quantity_ordered', 'ALL'
    # old_value - TEXT, optional.
    # Value before the change.
    old_value = Column(Text, nullable=True)
    # new_value - TEXT, optional.
    # Value after the change.
    new_value = Column(Text, nullable=True)
    
    # Snapshot of key fields at time of change
    # quantity - NUMERIC(12,2), optional.
    # Quantity at the time of change.
    quantity = Column(Numeric(12, 2), nullable=True)
    # unit_price - NUMERIC(14,2), optional.
    # Unit price at the time of change.
    unit_price = Column(Numeric(14, 2), nullable=True)
    # total_price - NUMERIC(14,2), optional.
    # Line total at the time of change.
    total_price = Column(Numeric(14, 2), nullable=True)
    
    # reason - TEXT, optional.
    # Why it was changed (mandatory for critical changes).
    reason = Column(Text, nullable=True)                 # Mandatory for CRITICAL level changes

    # Relationships
    po_item = relationship("POItem", back_populates="history")
    purchase_order = relationship("PurchaseOrder", foreign_keys=[po_id])

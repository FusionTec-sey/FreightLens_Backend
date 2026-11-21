from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from ...db import Base
from ...mixins import OrgMixin

# TABLE: Log of every status change on requests, orders, receipts and defects.
class OrderStatusHistory(OrgMixin, Base):
    __tablename__ = "order_status_history"
    __table_args__ = {'schema': 'containermgmt'}

    # id - INTEGER, primary key.
    # Unique row number.
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    
    # Entity reference
    # entity_type - VARCHAR(50), required, default PO.
    # Kind of record this row points at.
    entity_type = Column(String(50), nullable=False, default="PO")  # REQUEST, PO, RECEIPT, DEFECT
    # entity_id - INTEGER, required.
    # Id of the record this row points at.
    entity_id = Column(Integer, nullable=False, index=True)
    
    # po_id - INTEGER, foreign key -> containermgmt.purchase_orders.id, optional.
    # Purchase order (or RFQ) this row belongs to.
    po_id = Column(Integer, ForeignKey("containermgmt.purchase_orders.id", ondelete="CASCADE"), nullable=True, index=True)
    
    # from_status - VARCHAR(50), optional.
    # Status before the change.
    from_status = Column(String(50), nullable=True)
    # to_status - VARCHAR(50), required.
    # Status after the change.
    to_status = Column(String(50), nullable=False)
    # to_status_label - VARCHAR(100), optional.
    # Readable label of the new status.
    to_status_label = Column(String(100), nullable=True)
    
    # changed_by - INTEGER, foreign key -> usercredentials.users.id, optional.
    # User who changed it.
    changed_by = Column(Integer, ForeignKey("usercredentials.users.id"), nullable=True)
    # changed_at - TIMESTAMP WITH TIME ZONE, required.
    # When it changed.
    changed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    # notes - TEXT, optional.
    # Free-text remarks.
    notes = Column(Text, nullable=True)

    # Relationships
    purchase_order = relationship("PurchaseOrder", back_populates="status_history")
    user = relationship("User", foreign_keys=[changed_by], viewonly=True)

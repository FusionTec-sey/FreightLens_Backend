from sqlalchemy import Column, Integer, String, Text, ForeignKey, Numeric
from sqlalchemy.orm import relationship
from ...db import Base
from ...mixins import AuditMixin

class POItem(AuditMixin, Base):
    __tablename__ = "po_items"
    __table_args__ = {'schema': 'containermgmt'}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    po_id = Column(Integer, ForeignKey("containermgmt.purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    request_item_id = Column(Integer, ForeignKey("containermgmt.store_request_items.id"), nullable=True, index=True)
    
    item_code = Column(String(100), nullable=True)
    description = Column(Text, nullable=False)
    quantity_ordered = Column(Numeric(12, 2), nullable=False, default=1.0)
    quantity_packed = Column(Numeric(12, 2), nullable=False, default=0.0)
    quantity_received = Column(Numeric(12, 2), nullable=False, default=0.0)
    unit = Column(String(50), default="PCS")
    
    unit_price = Column(Numeric(14, 2), nullable=True)
    total_price = Column(Numeric(14, 2), nullable=True)
    currency = Column(String(10), default="USD")
    
    notes = Column(Text, nullable=True)
    product_id = Column(Integer, ForeignKey("containermgmt.products.id", ondelete="SET NULL"), nullable=True, index=True)

    # Relationships
    purchase_order = relationship("PurchaseOrder", back_populates="items")
    request_item = relationship("StoreRequestItem", back_populates="po_items")
    packing_items = relationship("PackingListItem", back_populates="po_item")
    receipt_items = relationship("ReceiptItem", back_populates="po_item")
    product = relationship("Product", back_populates="po_items")

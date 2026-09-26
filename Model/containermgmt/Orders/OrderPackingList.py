from sqlalchemy import Column, Integer, String, Text, Date, ForeignKey, Numeric
from sqlalchemy.orm import relationship
from ...db import Base
from ...mixins import AuditMixin, OrgMixin

class OrderPackingList(OrgMixin, AuditMixin, Base):
    __tablename__ = "order_packing_lists"
    __table_args__ = {'schema': 'containermgmt'}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    po_id = Column(Integer, ForeignKey("containermgmt.purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    
    packing_list_number = Column(String(100), nullable=False, index=True)
    supplier_invoice_ref = Column(String(100), nullable=True)
    package_count = Column(Integer, nullable=True)
    total_gross_weight = Column(Numeric(10, 2), nullable=True)
    total_cbm = Column(Numeric(10, 2), nullable=True)
    
    date_issued = Column(Date, nullable=True)
    status = Column(String(50), default="CONFIRMED")  # DRAFT, CONFIRMED, SHIPPED, RECEIVED
    notes = Column(Text, nullable=True)

    # Relationships
    purchase_order = relationship("PurchaseOrder", back_populates="packing_lists")
    items = relationship("PackingListItem", back_populates="packing_list", cascade="all, delete-orphan")
    receipts = relationship("GoodsReceipt", back_populates="packing_list")


class PackingListItem(AuditMixin, Base):
    __tablename__ = "order_packing_list_items"
    __table_args__ = {'schema': 'containermgmt'}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    packing_list_id = Column(Integer, ForeignKey("containermgmt.order_packing_lists.id", ondelete="CASCADE"), nullable=False, index=True)
    po_item_id = Column(Integer, ForeignKey("containermgmt.po_items.id"), nullable=True, index=True)
    
    item_code = Column(String(100), nullable=True)
    description = Column(Text, nullable=False)
    quantity_packed = Column(Numeric(12, 2), nullable=False, default=1.0)
    unit = Column(String(50), default="PCS")
    
    carton_numbers = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)

    # Relationships
    packing_list = relationship("OrderPackingList", back_populates="items")
    po_item = relationship("POItem", back_populates="packing_items")
    receipt_items = relationship("ReceiptItem", back_populates="packing_item")

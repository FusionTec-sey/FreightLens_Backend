from sqlalchemy import Column, Integer, String, Text, DateTime, Date, ForeignKey, Numeric, Boolean
from sqlalchemy.orm import relationship
from ...db import Base
from ...mixins import AuditMixin, OrgMixin

class GoodsReceipt(OrgMixin, AuditMixin, Base):
    __tablename__ = "goods_receipts"
    __table_args__ = {'schema': 'containermgmt'}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    receipt_number = Column(String(100), unique=True, nullable=False, index=True)  # e.g. GRN-2026-0001
    
    po_id = Column(Integer, ForeignKey("containermgmt.purchase_orders.id"), nullable=False, index=True)
    packing_list_id = Column(Integer, ForeignKey("containermgmt.order_packing_lists.id"), nullable=True, index=True)
    container_id = Column(Integer, ForeignKey("containermgmt.container_details.Container_ID"), nullable=True, index=True)
    
    warehouse_location = Column(String(150), nullable=True)
    received_date = Column(Date, nullable=False)
    received_by = Column(Integer, ForeignKey("usercredentials.users.id"), nullable=True)
    
    # Status: DRAFT, SUBMITTED, DISCREPANCY, VERIFIED
    status = Column(String(50), default="DRAFT", index=True)
    has_discrepancies = Column(Boolean, default=False)
    
    notes = Column(Text, nullable=True)
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    # Zero means legacy/unreviewed: old drafts may already have affected totals.
    posting_version = Column(Integer, nullable=False, default=0, server_default="0")

    # Relationships
    purchase_order = relationship("PurchaseOrder", back_populates="receipts")
    packing_list = relationship("OrderPackingList", back_populates="receipts")
    container = relationship("ContainerDetails", foreign_keys=[container_id], lazy="joined")
    receiver = relationship("User", foreign_keys=[received_by], viewonly=True)
    items = relationship("ReceiptItem", back_populates="receipt", cascade="all, delete-orphan")
    defects = relationship("DefectReport", back_populates="receipt")


class ReceiptItem(AuditMixin, Base):
    __tablename__ = "goods_receipt_items"
    __table_args__ = {'schema': 'containermgmt'}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    receipt_id = Column(Integer, ForeignKey("containermgmt.goods_receipts.id", ondelete="CASCADE"), nullable=False, index=True)
    po_item_id = Column(Integer, ForeignKey("containermgmt.po_items.id"), nullable=True, index=True)
    packing_item_id = Column(Integer, ForeignKey("containermgmt.order_packing_list_items.id"), nullable=True, index=True)
    
    description = Column(Text, nullable=False)
    expected_quantity = Column(Numeric(12, 2), nullable=False, default=0.0)
    received_quantity = Column(Numeric(12, 2), nullable=False, default=0.0)
    
    missing_quantity = Column(Numeric(12, 2), default=0.0)
    excess_quantity = Column(Numeric(12, 2), default=0.0)
    damaged_quantity = Column(Numeric(12, 2), default=0.0)
    incorrect_quantity = Column(Numeric(12, 2), default=0.0)
    
    unit = Column(String(50), default="PCS")
    condition_ok = Column(Boolean, default=True)
    notes = Column(Text, nullable=True)
    photo_url = Column(String(500), nullable=True)

    # Relationships
    receipt = relationship("GoodsReceipt", back_populates="items")
    po_item = relationship("POItem", back_populates="receipt_items")
    packing_item = relationship("PackingListItem", back_populates="receipt_items")

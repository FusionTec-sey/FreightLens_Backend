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
    
    # ── Multi-Stage Prices ───────────────────────────────────────────────
    draft_unit_price = Column(Numeric(14, 2), nullable=True)       # Estimated price during Draft
    approved_unit_price = Column(Numeric(14, 2), nullable=True)    # Internal signed-off price
    po_unit_price = Column(Numeric(14, 2), nullable=True)          # Price when official PO was issued
    proforma_unit_price = Column(Numeric(14, 2), nullable=True)    # Final price on Proforma invoice

    # ── Lifecycle Item Status ────────────────────────────────────────────
    # ACTIVE, USER_REMOVED, VENDOR_REJECTED, SUBSTITUTED
    item_status = Column(String(30), nullable=False, default="ACTIVE")
    removed_at_stage = Column(String(30), nullable=True)
    substituted_by_id = Column(Integer, ForeignKey("containermgmt.po_items.id", ondelete="SET NULL"), nullable=True)
    original_item_id = Column(Integer, ForeignKey("containermgmt.po_items.id", ondelete="SET NULL"), nullable=True)

    notes = Column(Text, nullable=True)
    product_id = Column(Integer, ForeignKey("containermgmt.products.id", ondelete="SET NULL"), nullable=True, index=True)

    # ── RFQ Lineage & Split-Award Fields ─────────────────────────────────
    source_rfq_item_id = Column(Integer, ForeignKey("containermgmt.po_items.id", ondelete="SET NULL"), nullable=True)
    awarded_vendor_id = Column(Integer, ForeignKey("containermgmt.supplier.supplier_id"), nullable=True)
    awarded_quote_id = Column(Integer, ForeignKey("containermgmt.vendor_quotes.id"), nullable=True)

    # Relationships
    purchase_order = relationship("PurchaseOrder", back_populates="items")
    request_item = relationship("StoreRequestItem", back_populates="po_items")
    packing_items = relationship("PackingListItem", back_populates="po_item")
    receipt_items = relationship("ReceiptItem", back_populates="po_item")
    product = relationship("Product", back_populates="po_items")
    history = relationship("POItemHistory", back_populates="po_item", cascade="all, delete-orphan", order_by="POItemHistory.created_at.desc()")
    source_rfq_item = relationship("POItem", remote_side=[id], foreign_keys=[source_rfq_item_id])

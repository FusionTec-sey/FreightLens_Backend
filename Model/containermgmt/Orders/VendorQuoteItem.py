from sqlalchemy import Column, Integer, String, Boolean, Date, Text, ForeignKey, Numeric
from sqlalchemy.orm import relationship
from ...db import Base
from ...mixins import AuditMixin

class VendorQuoteItem(AuditMixin, Base):
    __tablename__ = "vendor_quote_items"
    __table_args__ = {'schema': 'containermgmt'}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    vendor_quote_id = Column(Integer, ForeignKey("containermgmt.vendor_quotes.id", ondelete="CASCADE"), nullable=False, index=True)
    po_item_id = Column(Integer, ForeignKey("containermgmt.po_items.id", ondelete="SET NULL"), nullable=True, index=True)
    
    inventory_product_id = Column(Integer, ForeignKey("containermgmt.products.id", ondelete="SET NULL"), nullable=True, index=True)
    item_code = Column(String(100), nullable=True)
    description = Column(Text, nullable=False)
    
    quantity_quoted = Column(Numeric(12, 2), nullable=False)
    unit_price = Column(Numeric(14, 2), nullable=False)
    total_price = Column(Numeric(14, 2), nullable=False)
    currency = Column(String(10), default="USD")
    
    availability = Column(String(30), default="AVAILABLE") # AVAILABLE, PARTIAL, OUT_OF_STOCK, SUBSTITUTE_OFFERED
    lead_time_days = Column(Integer, nullable=True)
    
    is_substitute = Column(Boolean, default=False)
    is_awarded = Column(Boolean, default=False)
    original_item_id = Column(Integer, ForeignKey("containermgmt.po_items.id", ondelete="SET NULL"), nullable=True)
    notes = Column(Text, nullable=True)
    
    # Historical Benchmark (populated via QuoteComparisonService from previous POs)
    last_purchase_price = Column(Numeric(14, 2), nullable=True)
    last_purchase_date = Column(Date, nullable=True)
    last_purchase_po_id = Column(Integer, ForeignKey("containermgmt.purchase_orders.id", ondelete="SET NULL"), nullable=True)
    price_trend = Column(String(10), nullable=True)        # UP, DOWN, SAME

    # Relationships
    vendor_quote = relationship("VendorQuote", back_populates="items")
    po_item = relationship("POItem", foreign_keys=[po_item_id])
    product = relationship("Product", foreign_keys=[inventory_product_id])
    last_purchase_po = relationship("PurchaseOrder", foreign_keys=[last_purchase_po_id])

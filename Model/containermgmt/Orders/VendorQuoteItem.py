from sqlalchemy import Column, Integer, String, Boolean, Date, Text, ForeignKey, Numeric
from sqlalchemy.orm import relationship
from ...db import Base
from ...mixins import AuditMixin

# TABLE: Line prices within a vendor quote.
class VendorQuoteItem(AuditMixin, Base):
    __tablename__ = "vendor_quote_items"
    __table_args__ = {'schema': 'containermgmt'}

    # id - INTEGER, primary key.
    # Unique row number.
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    # vendor_quote_id - INTEGER, foreign key -> containermgmt.vendor_quotes.id, required.
    # Quote this line belongs to.
    vendor_quote_id = Column(Integer, ForeignKey("containermgmt.vendor_quotes.id", ondelete="CASCADE"), nullable=False, index=True)
    # po_item_id - INTEGER, foreign key -> containermgmt.po_items.id, optional.
    # RFQ line being quoted.
    po_item_id = Column(Integer, ForeignKey("containermgmt.po_items.id", ondelete="SET NULL"), nullable=True, index=True)
    
    # inventory_product_id - INTEGER, foreign key -> containermgmt.products.id, optional.
    # Catalogue product matching the quoted item.
    inventory_product_id = Column(Integer, ForeignKey("containermgmt.products.id", ondelete="SET NULL"), nullable=True, index=True)
    # item_code - VARCHAR(100), optional.
    # Item/article code for this line.
    item_code = Column(String(100), nullable=True)
    # description - TEXT, required.
    # Free-text description.
    description = Column(Text, nullable=False)
    
    # quantity_quoted - NUMERIC(12,2), required.
    # Quantity the vendor quoted.
    quantity_quoted = Column(Numeric(12, 2), nullable=False)
    # unit_price - NUMERIC(14,2), required.
    # Quoted unit price.
    unit_price = Column(Numeric(14, 2), nullable=False)
    # total_price - NUMERIC(14,2), required.
    # Quoted line total.
    total_price = Column(Numeric(14, 2), nullable=False)
    # currency - VARCHAR(10), optional, default USD.
    # Currency code of the amounts on this row (e.g. USD, SCR).
    currency = Column(String(10), default="USD")
    
    # availability - VARCHAR(30), optional, default AVAILABLE.
    # AVAILABLE, PARTIAL, SUBSTITUTE_OFFERED, OUT_OF_STOCK or NOT_QUOTED.
    availability = Column(String(30), default="AVAILABLE") # AVAILABLE, PARTIAL, SUBSTITUTE_OFFERED, OUT_OF_STOCK (carried, cannot supply now), NOT_QUOTED (not offered at all)
    # lead_time_days - INTEGER, optional.
    # Lead time for this line.
    lead_time_days = Column(Integer, nullable=True)
    
    # is_substitute - BOOLEAN, optional, default False.
    # True if the vendor offers a substitute item.
    is_substitute = Column(Boolean, default=False)
    # is_awarded - BOOLEAN, optional, default False.
    # True if this line won the award.
    is_awarded = Column(Boolean, default=False)
    # original_item_id - INTEGER, foreign key -> containermgmt.po_items.id, optional.
    # RFQ line a substitute replaces.
    original_item_id = Column(Integer, ForeignKey("containermgmt.po_items.id", ondelete="SET NULL"), nullable=True)
    # notes - TEXT, optional.
    # Free-text remarks.
    notes = Column(Text, nullable=True)
    
    # Historical Benchmark (populated via QuoteComparisonService from previous POs)
    # last_purchase_price - NUMERIC(14,2), optional.
    # Price paid on the previous order (benchmark).
    last_purchase_price = Column(Numeric(14, 2), nullable=True)
    # last_purchase_date - DATE, optional.
    # Date of the previous purchase.
    last_purchase_date = Column(Date, nullable=True)
    # last_purchase_po_id - INTEGER, foreign key -> containermgmt.purchase_orders.id, optional.
    # Previous order used for the benchmark.
    last_purchase_po_id = Column(Integer, ForeignKey("containermgmt.purchase_orders.id", ondelete="SET NULL"), nullable=True)
    # price_trend - VARCHAR(10), optional.
    # UP, DOWN or SAME versus last purchase.
    price_trend = Column(String(10), nullable=True)        # UP, DOWN, SAME

    # Relationships
    vendor_quote = relationship("VendorQuote", back_populates="items")
    po_item = relationship("POItem", foreign_keys=[po_item_id])
    product = relationship("Product", foreign_keys=[inventory_product_id])
    last_purchase_po = relationship("PurchaseOrder", foreign_keys=[last_purchase_po_id])

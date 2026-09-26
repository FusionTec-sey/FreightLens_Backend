from sqlalchemy import Column, Integer, String, Boolean, Date, Text, ForeignKey, Numeric
from sqlalchemy.orm import relationship
from ...db import Base
from ...mixins import AuditMixin, OrgMixin

class VendorQuote(OrgMixin, AuditMixin, Base):
    __tablename__ = "vendor_quotes"
    __table_args__ = {'schema': 'containermgmt'}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    po_id = Column(Integer, ForeignKey("containermgmt.purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    supplier_id = Column(Integer, ForeignKey("containermgmt.supplier.supplier_id"), nullable=False, index=True)
    
    quote_reference = Column(String(100), nullable=True)  # Vendor's quotation / proforma ref#
    quote_date = Column(Date, nullable=False)
    valid_until = Column(Date, nullable=True)
    total_quoted_amount = Column(Numeric(14, 2), nullable=False)
    currency = Column(String(10), default="USD")
    delivery_lead_time_days = Column(Integer, nullable=True)
    payment_terms = Column(String(255), nullable=True)
    shipping_terms = Column(String(50), nullable=True)    # FOB, CIF, EXW, DDP, CFR
    status = Column(String(30), default="PENDING")        # PENDING, ACCEPTED, REJECTED, SUPERSEDED
    rejection_reason = Column(Text, nullable=True)
    rank = Column(Integer, nullable=True)                 # Ranking score e.g. 1 = best
    score_notes = Column(Text, nullable=True)             # Analysis notes (e.g., "Best lead time")

    # Relationships
    purchase_order = relationship("PurchaseOrder", back_populates="quotes", foreign_keys=[po_id])
    supplier = relationship("Supplier", foreign_keys=[supplier_id], lazy="joined")
    items = relationship("VendorQuoteItem", back_populates="vendor_quote", cascade="all, delete-orphan")
    documents = relationship("OrderDocument", back_populates="vendor_quote", cascade="all, delete-orphan")

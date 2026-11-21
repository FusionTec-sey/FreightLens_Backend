from sqlalchemy import Column, Integer, String, Boolean, Date, Text, ForeignKey, Numeric
from sqlalchemy.orm import relationship
from ...db import Base
from ...mixins import AuditMixin, OrgMixin

# TABLE: A vendor's reply to an RFQ.
class VendorQuote(OrgMixin, AuditMixin, Base):
    __tablename__ = "vendor_quotes"
    __table_args__ = {'schema': 'containermgmt'}

    # id - INTEGER, primary key.
    # Unique row number.
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    # po_id - INTEGER, foreign key -> containermgmt.purchase_orders.id, required.
    # Purchase order (or RFQ) this row belongs to.
    po_id = Column(Integer, ForeignKey("containermgmt.purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    # supplier_id - INTEGER, foreign key -> containermgmt.supplier.supplier_id, required.
    # Vendor this row refers to (supplier table).
    supplier_id = Column(Integer, ForeignKey("containermgmt.supplier.supplier_id"), nullable=False, index=True)
    
    # quote_reference - VARCHAR(100), optional.
    # Vendor's quotation/proforma reference.
    quote_reference = Column(String(100), nullable=True)  # Vendor's quotation / proforma ref#
    # quote_date - DATE, required.
    # Date of the quote.
    quote_date = Column(Date, nullable=False)
    # valid_until - DATE, optional.
    # Date the quote expires.
    valid_until = Column(Date, nullable=True)
    # total_quoted_amount - NUMERIC(14,2), required.
    # Total price quoted.
    total_quoted_amount = Column(Numeric(14, 2), nullable=False)
    # currency - VARCHAR(10), optional, default USD.
    # Currency code of the amounts on this row (e.g. USD, SCR).
    currency = Column(String(10), default="USD")
    # delivery_lead_time_days - INTEGER, optional.
    # Promised delivery time in days.
    delivery_lead_time_days = Column(Integer, nullable=True)
    # payment_terms - VARCHAR(255), optional.
    # Payment terms offered.
    payment_terms = Column(String(255), nullable=True)
    # shipping_terms - VARCHAR(50), optional.
    # Incoterm: FOB, CIF, EXW, DDP, CFR...
    shipping_terms = Column(String(50), nullable=True)    # FOB, CIF, EXW, DDP, CFR
    # status - VARCHAR(30), optional, default PENDING.
    # PENDING, ACCEPTED, REJECTED or SUPERSEDED.
    status = Column(String(30), default="PENDING")        # PENDING, ACCEPTED, REJECTED, SUPERSEDED
    # rejection_reason - TEXT, optional.
    # Why the quote was rejected.
    rejection_reason = Column(Text, nullable=True)
    # rank - INTEGER, optional.
    # Ranking among quotes (1 = best).
    rank = Column(Integer, nullable=True)                 # Ranking score e.g. 1 = best
    # score_notes - TEXT, optional.
    # Analysis notes, e.g. 'Best lead time'.
    score_notes = Column(Text, nullable=True)             # Analysis notes (e.g., "Best lead time")

    # Relationships
    purchase_order = relationship("PurchaseOrder", back_populates="quotes", foreign_keys=[po_id])
    supplier = relationship("Supplier", foreign_keys=[supplier_id], lazy="joined")
    items = relationship("VendorQuoteItem", back_populates="vendor_quote", cascade="all, delete-orphan")
    documents = relationship("OrderDocument", back_populates="vendor_quote", cascade="all, delete-orphan")

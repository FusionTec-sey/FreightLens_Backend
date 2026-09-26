import uuid
from sqlalchemy import Column, Integer, String, Text, ForeignKey, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from ...db import Base
from ...mixins import AuditMixin, OrgMixin

class OrderDocument(OrgMixin, AuditMixin, Base):
    __tablename__ = "order_documents"
    __table_args__ = {'schema': 'containermgmt'}

    # Use native UUID in Postgres / String UUID representation in Python for security & object storage correlation
    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    
    # Entity reference
    entity_type = Column(String(50), nullable=False, index=True)  # REQUEST, RFQ, VENDOR_QUOTE, PO, PAYMENT, PACKING_LIST, RECEIPT, DEFECT, GENERAL
    entity_id = Column(Integer, nullable=True, index=True)
    
    po_id = Column(Integer, ForeignKey("containermgmt.purchase_orders.id", ondelete="CASCADE"), nullable=True, index=True)
    payment_id = Column(Integer, ForeignKey("containermgmt.order_payments.id", ondelete="SET NULL"), nullable=True, index=True)
    vendor_quote_id = Column(Integer, ForeignKey("containermgmt.vendor_quotes.id", ondelete="SET NULL"), nullable=True, index=True)
    
    # Document category: REQUEST_SPEC, QUOTATION, PROFORMA_INVOICE, PO_GENERATED, PO_SENT_SIGNED,
    # ADVANCE_PAYMENT_PROOF, BALANCE_PAYMENT_PROOF, PRODUCTION_INSPECTION, PACKING_LIST,
    # BILL_OF_LADING, RECEIVING_PROOF, DEFECT_IMAGE, REFUND_CREDIT_NOTE, OTHER
    doc_type = Column(String(50), nullable=False, index=True)
    
    title = Column(String(255), nullable=True)
    file_name = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)  # RustFS blob storage key / path
    file_size = Column(Integer, nullable=True)
    mime_type = Column(String(100), nullable=True)
    
    # Confidentiality: True = only Accounts/Admin can view, False = Stores & Warehouse can also view if authorized
    is_confidential = Column(Boolean, default=False)
    notes = Column(Text, nullable=True)

    # Relationships
    purchase_order = relationship("PurchaseOrder", back_populates="documents")
    payment = relationship("OrderPayment", foreign_keys=[payment_id], back_populates="documents")
    vendor_quote = relationship("VendorQuote", foreign_keys=[vendor_quote_id], back_populates="documents")

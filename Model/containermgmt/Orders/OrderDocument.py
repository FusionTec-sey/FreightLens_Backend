import uuid
from sqlalchemy import Column, Integer, String, Text, ForeignKey, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from ...db import Base
from ...mixins import AuditMixin, OrgMixin

# TABLE: Every uploaded file in the procurement flow (quotes, PO PDFs, payment proofs, B/L, photos).
class OrderDocument(OrgMixin, AuditMixin, Base):
    __tablename__ = "order_documents"
    __table_args__ = {'schema': 'containermgmt'}

    # Use native UUID in Postgres / String UUID representation in Python for security & object storage correlation
    # id - UUID, primary key.
    # Unique file id (UUID).
    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    
    # Entity reference
    # entity_type - VARCHAR(50), required.
    # What it is attached to: REQUEST, RFQ, VENDOR_QUOTE, PO, PAYMENT, PACKING_LIST, RECEIPT, DEFECT,
    # GENERAL.
    entity_type = Column(String(50), nullable=False, index=True)  # REQUEST, RFQ, VENDOR_QUOTE, PO, PAYMENT, PACKING_LIST, RECEIPT, DEFECT, GENERAL
    # entity_id - INTEGER, optional.
    # Id of the record it is attached to.
    entity_id = Column(Integer, nullable=True, index=True)
    
    # po_id - INTEGER, foreign key -> containermgmt.purchase_orders.id, optional.
    # Purchase order (or RFQ) this row belongs to.
    po_id = Column(Integer, ForeignKey("containermgmt.purchase_orders.id", ondelete="CASCADE"), nullable=True, index=True)
    # payment_id - INTEGER, foreign key -> containermgmt.order_payments.id, optional.
    # Payment this file is proof for.
    payment_id = Column(Integer, ForeignKey("containermgmt.order_payments.id", ondelete="SET NULL"), nullable=True, index=True)
    # proforma_id - INTEGER, foreign key -> containermgmt.proforma_invoices.id, optional.
    # Proforma invoice this file belongs to.
    proforma_id = Column(Integer, ForeignKey("containermgmt.proforma_invoices.id", ondelete="SET NULL"), nullable=True, index=True)
    # vendor_quote_id - INTEGER, foreign key -> containermgmt.vendor_quotes.id, optional.
    # Vendor quote this file belongs to.
    vendor_quote_id = Column(Integer, ForeignKey("containermgmt.vendor_quotes.id", ondelete="SET NULL"), nullable=True, index=True)
    
    # Document category: REQUEST_SPEC, QUOTATION, PROFORMA_INVOICE, PO_GENERATED, PO_SENT_SIGNED,
    # ADVANCE_PAYMENT_PROOF, BALANCE_PAYMENT_PROOF, PRODUCTION_INSPECTION, PACKING_LIST,
    # BILL_OF_LADING, RECEIVING_PROOF, DEFECT_IMAGE, REFUND_CREDIT_NOTE, OTHER
    # doc_type - VARCHAR(50), required.
    # Document category: QUOTATION, PROFORMA_INVOICE, PO_GENERATED, ADVANCE_PAYMENT_PROOF,
    # BILL_OF_LADING, DEFECT_IMAGE, OTHER...
    doc_type = Column(String(50), nullable=False, index=True)
    
    # title - VARCHAR(255), optional.
    # Display title.
    title = Column(String(255), nullable=True)
    # file_name - VARCHAR(255), required.
    # Original file name.
    file_name = Column(String(255), nullable=False)
    # file_path - VARCHAR(500), required.
    # Storage key/path of the file.
    file_path = Column(String(500), nullable=False)  # RustFS blob storage key / path
    # file_size - INTEGER, optional.
    # Size in bytes.
    file_size = Column(Integer, nullable=True)
    # mime_type - VARCHAR(100), optional.
    # File type, e.g. application/pdf.
    mime_type = Column(String(100), nullable=True)
    
    # Confidentiality: True = only Accounts/Admin can view, False = Stores & Warehouse can also view if authorized
    # is_confidential - BOOLEAN, optional, default False.
    # True = only Accounts/Admin can view; False = Stores & Warehouse may also view.
    is_confidential = Column(Boolean, default=False)
    # notes - TEXT, optional.
    # Free-text remarks.
    notes = Column(Text, nullable=True)

    # Relationships
    purchase_order = relationship("PurchaseOrder", back_populates="documents")
    payment = relationship("OrderPayment", foreign_keys=[payment_id], back_populates="documents")
    vendor_quote = relationship("VendorQuote", foreign_keys=[vendor_quote_id], back_populates="documents")

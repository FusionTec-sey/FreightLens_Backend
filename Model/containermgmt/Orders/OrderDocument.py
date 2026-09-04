from sqlalchemy import Column, Integer, String, Text, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from ...db import Base
from ...mixins import AuditMixin

class OrderDocument(AuditMixin, Base):
    __tablename__ = "order_documents"
    __table_args__ = {'schema': 'containermgmt'}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    
    # Entity reference
    entity_type = Column(String(50), nullable=False, index=True)  # REQUEST, PO, PACKING_LIST, RECEIPT, DEFECT
    entity_id = Column(Integer, nullable=False, index=True)
    
    po_id = Column(Integer, ForeignKey("containermgmt.purchase_orders.id", ondelete="CASCADE"), nullable=True, index=True)
    
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

    # Relationship
    purchase_order = relationship("PurchaseOrder", back_populates="documents")

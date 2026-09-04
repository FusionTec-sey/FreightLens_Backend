from sqlalchemy import Column, Integer, String, Text, Date, ForeignKey, Numeric
from sqlalchemy.orm import relationship
from ...db import Base
from ...mixins import AuditMixin

class OrderPayment(AuditMixin, Base):
    __tablename__ = "order_payments"
    __table_args__ = {'schema': 'containermgmt'}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    po_id = Column(Integer, ForeignKey("containermgmt.purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Payment Type: ADVANCE, PROGRESS, BALANCE, FULL
    payment_type = Column(String(50), nullable=False, default="ADVANCE")
    
    amount = Column(Numeric(14, 2), nullable=False)
    currency = Column(String(10), default="USD")
    exchange_rate = Column(Numeric(10, 4), default=1.0)
    amount_local = Column(Numeric(14, 2), nullable=True)  # SCR amount
    
    due_date = Column(Date, nullable=True)
    paid_date = Column(Date, nullable=True)
    
    # Status: PENDING, PAID, CANCELLED
    status = Column(String(50), default="PAID")
    
    payment_method = Column(String(100), nullable=True)  # TT / Bank Transfer, LC, Cheque, Cash
    reference_number = Column(String(100), nullable=True)  # Bank ref / transaction ID
    
    evidence_doc_id = Column(Integer, ForeignKey("containermgmt.order_documents.id"), nullable=True)
    notes = Column(Text, nullable=True)

    # Relationships
    purchase_order = relationship("PurchaseOrder", back_populates="payments")
    evidence_doc = relationship("OrderDocument", foreign_keys=[evidence_doc_id])

from sqlalchemy import Column, Integer, String, Text, Date, ForeignKey, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from ...db import Base
from ...mixins import AuditMixin, OrgMixin

# TABLE: Each payment made (or due) against a proforma invoice / purchase order.
class OrderPayment(OrgMixin, AuditMixin, Base):
    __tablename__ = "order_payments"
    __table_args__ = {'schema': 'containermgmt'}

    # id - INTEGER, primary key.
    # Unique row number.
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    # po_id - INTEGER, foreign key -> containermgmt.purchase_orders.id, required.
    # Purchase order (or RFQ) this row belongs to.
    po_id = Column(Integer, ForeignKey("containermgmt.purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # The proforma invoice this payment settles. po_id stays set as well (it is
    # the proforma's PO), so registers and ledgers keyed on the PO keep working;
    # rows recorded before proformas existed have only po_id.
    # proforma_id - INTEGER, foreign key -> containermgmt.proforma_invoices.id, optional.
    # Proforma invoice this payment settles.
    proforma_id = Column(Integer, ForeignKey("containermgmt.proforma_invoices.id", ondelete="SET NULL"), nullable=True, index=True)

    # Payment Type: ADVANCE, PROGRESS, BALANCE, FULL
    # payment_type - VARCHAR(50), required, default ADVANCE.
    # ADVANCE, PROGRESS, BALANCE or FULL.
    payment_type = Column(String(50), nullable=False, default="ADVANCE")
    
    # amount - NUMERIC(14,2), required.
    # Amount paid, in the payment currency.
    amount = Column(Numeric(14, 2), nullable=False)
    # currency - VARCHAR(10), optional, default USD.
    # Currency code of the amounts on this row (e.g. USD, SCR).
    currency = Column(String(10), default="USD")
    # exchange_rate - NUMERIC(10,4), optional, default 1.0.
    # Rate to local currency at payment time.
    exchange_rate = Column(Numeric(10, 4), default=1.0)
    # amount_local - NUMERIC(14,2), optional.
    # Amount in local currency (SCR).
    amount_local = Column(Numeric(14, 2), nullable=True)  # SCR amount
    # base_currency - VARCHAR(10), optional.
    # Company reporting currency that the *_base amounts are converted into.
    base_currency = Column(String(10), nullable=True)
    # base_amount - NUMERIC(14,2), optional.
    # Amount in the company base currency.
    base_amount = Column(Numeric(14, 2), nullable=True)
    
    # due_date - DATE, optional.
    # Date the payment is due.
    due_date = Column(Date, nullable=True)
    # paid_date - DATE, optional.
    # Date it was actually paid.
    paid_date = Column(Date, nullable=True)
    
    # Status: PENDING, PAID, CANCELLED
    # status - VARCHAR(50), optional, default PAID.
    # PENDING, PAID or CANCELLED.
    status = Column(String(50), default="PAID")
    
    # payment_method - VARCHAR(100), optional.
    # TT / Bank Transfer, LC, Cheque, Cash...
    payment_method = Column(String(100), nullable=True)  # TT / Bank Transfer, LC, Cheque, Cash
    # reference_number - VARCHAR(100), optional.
    # Bank reference / transaction id.
    reference_number = Column(String(100), nullable=True)  # Bank ref / transaction ID
    
    # evidence_doc_id - UUID, foreign key -> containermgmt.order_documents.id, optional.
    # Uploaded proof of payment.
    evidence_doc_id = Column(UUID(as_uuid=False), ForeignKey("containermgmt.order_documents.id", ondelete="SET NULL"), nullable=True)
    # notes - TEXT, optional.
    # Free-text remarks.
    notes = Column(Text, nullable=True)

    # Relationships
    purchase_order = relationship("PurchaseOrder", back_populates="payments")
    proforma = relationship("ProformaInvoice", back_populates="payments", foreign_keys=[proforma_id])
    evidence_doc = relationship("OrderDocument", foreign_keys=[evidence_doc_id])
    documents = relationship("OrderDocument", foreign_keys="[OrderDocument.payment_id]", back_populates="payment", cascade="all, delete-orphan")

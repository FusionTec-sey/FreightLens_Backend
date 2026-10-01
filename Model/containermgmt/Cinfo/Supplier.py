from sqlalchemy import Column, String, Integer, Numeric, Boolean, Text, ForeignKey
from sqlalchemy.orm import relationship
from ...db import Base
from ...mixins import AuditMixin
from ..MasterData.PaymentTerm import PaymentTerm

class Supplier(AuditMixin, Base):
    __tablename__ = 'supplier'
    __table_args__ = {'schema': 'containermgmt'}

    supplier_id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("usercredentials.organisations.id"), nullable=False, index=True)
    is_shared = Column(Boolean, default=False, nullable=False, index=True)
    name = Column(String(255))
    code = Column(String(50), nullable=True)
    address = Column(String(255), nullable=True)
    email = Column(String(100), nullable=True)
    phone = Column(String(50), nullable=True)
    contact_person = Column(String(100), nullable=True)
    country = Column(String(100), nullable=True)
    logo_url = Column(String(500), nullable=True)
    default_currency = Column(String(10), default="USD", nullable=True)
    default_payment_term_id = Column(Integer, ForeignKey("containermgmt.payment_terms.id", ondelete="SET NULL"), nullable=True)
    variance_threshold_pct = Column(Numeric(5, 2), default=2.0, nullable=True)
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    
    bill_of_landings = relationship("BillOfLanding", back_populates="supplier_rel")
    payment_term = relationship("PaymentTerm", foreign_keys=[default_payment_term_id], lazy="joined")
    organisation = relationship("Organisation", foreign_keys=[org_id], viewonly=True)


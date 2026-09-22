from sqlalchemy import Column, String, Integer, Boolean, DateTime, Numeric, Text, func
from ...db import Base
from ...mixins import AuditMixin

class PaymentTerm(AuditMixin, Base):
    __tablename__ = 'payment_terms'
    __table_args__ = {'schema': 'containermgmt'}

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(50), unique=True, nullable=False) # e.g. ADV_30_BL_70, NET_30, ADV_100
    name = Column(String(100), nullable=False)             # e.g. 30% Advance, 70% against B/L
    description = Column(Text, nullable=True)
    advance_pct = Column(Numeric(5, 2), default=0.00, nullable=False)
    progress_pct = Column(Numeric(5, 2), default=0.00, nullable=False)
    balance_pct = Column(Numeric(5, 2), default=100.00, nullable=False)
    balance_trigger = Column(String(50), default="ON_BL", nullable=False) # ON_BL, ON_ARRIVAL, ON_DISPATCH, PI_CONFIRMATION, NET_DAYS
    credit_days = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

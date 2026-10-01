from sqlalchemy import Boolean, Column, Integer, Numeric, String, Text, UniqueConstraint
from ...db import Base
from ...mixins import AuditMixin, OrgMixin

class PaymentTerm(OrgMixin, AuditMixin, Base):
    __tablename__ = 'payment_terms'
    __table_args__ = (
        UniqueConstraint("org_id", "code", name="uq_payment_terms_org_code"),
        {'schema': 'containermgmt'},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(50), nullable=False, index=True) # e.g. ADV_30_BL_70, NET_30, ADV_100
    is_shared = Column(Boolean, default=False, nullable=False, index=True)
    name = Column(String(100), nullable=False)             # e.g. 30% Advance, 70% against B/L
    description = Column(Text, nullable=True)
    advance_pct = Column(Numeric(5, 2), default=0.00, nullable=False)
    progress_pct = Column(Numeric(5, 2), default=0.00, nullable=False)
    balance_pct = Column(Numeric(5, 2), default=100.00, nullable=False)
    balance_trigger = Column(String(50), default="ON_BL", nullable=False) # ON_BL, ON_ARRIVAL, ON_DISPATCH, PI_CONFIRMATION, NET_DAYS
    credit_days = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

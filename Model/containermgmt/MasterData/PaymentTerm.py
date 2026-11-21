from sqlalchemy import Boolean, Column, Integer, Numeric, String, Text, UniqueConstraint
from ...db import Base
from ...mixins import AuditMixin, OrgMixin

# TABLE: Reusable payment terms, e.g. 30% advance, 70% against B/L.
class PaymentTerm(OrgMixin, AuditMixin, Base):
    __tablename__ = 'payment_terms'
    __table_args__ = (
        UniqueConstraint("org_id", "code", name="uq_payment_terms_org_code"),
        {'schema': 'containermgmt'},
    )

    # id - INTEGER, primary key.
    # Unique row number.
    id = Column(Integer, primary_key=True, autoincrement=True)
    # code - VARCHAR(50), required.
    # Short code, unique per company (e.g. ADV_30_BL_70).
    code = Column(String(50), nullable=False, index=True) # e.g. ADV_30_BL_70, NET_30, ADV_100
    # is_shared - BOOLEAN, required, default False.
    # True = visible to every company, not only the owning one.
    is_shared = Column(Boolean, default=False, nullable=False, index=True)
    # name - VARCHAR(100), required.
    # Readable name.
    name = Column(String(100), nullable=False)             # e.g. 30% Advance, 70% against B/L
    # description - TEXT, optional.
    # Free-text description.
    description = Column(Text, nullable=True)
    # advance_pct - NUMERIC(5,2), required, default 0.00.
    # % paid up front.
    advance_pct = Column(Numeric(5, 2), default=0.00, nullable=False)
    # progress_pct - NUMERIC(5,2), required, default 0.00.
    # % paid during production.
    progress_pct = Column(Numeric(5, 2), default=0.00, nullable=False)
    # balance_pct - NUMERIC(5,2), required, default 100.00.
    # % paid at the balance trigger.
    balance_pct = Column(Numeric(5, 2), default=100.00, nullable=False)
    # balance_trigger - VARCHAR(50), required, default ON_BL.
    # Event that makes the balance due: ON_BL, ON_ARRIVAL, ON_DISPATCH, PI_CONFIRMATION or NET_DAYS.
    balance_trigger = Column(String(50), default="ON_BL", nullable=False) # ON_BL, ON_ARRIVAL, ON_DISPATCH, PI_CONFIRMATION, NET_DAYS
    # credit_days - INTEGER, required, default 0.
    # Days of credit after the trigger.
    credit_days = Column(Integer, default=0, nullable=False)
    # is_active - BOOLEAN, required, default True.
    # False hides the record from use without deleting it.
    is_active = Column(Boolean, default=True, nullable=False)

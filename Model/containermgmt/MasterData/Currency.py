from sqlalchemy import Column, String, Integer, Boolean, DateTime, Date, Numeric, ForeignKey, func
from ...db import Base
from ...mixins import AuditMixin

class Currency(Base):
    __tablename__ = 'currencies'
    __table_args__ = {'schema': 'containermgmt'}

    code = Column(String(10), primary_key=True)  # ISO 4217 code, e.g. USD, SCR, EUR
    name = Column(String(100), nullable=False)
    symbol = Column(String(10), nullable=True)
    decimals = Column(Integer, default=2, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class CurrencyExchangeRate(AuditMixin, Base):
    __tablename__ = 'currency_exchange_rates'
    __table_args__ = {'schema': 'containermgmt'}

    id = Column(Integer, primary_key=True, autoincrement=True)
    org_id = Column(Integer, nullable=True, index=True) # None indicates global standard rate, otherwise specific to entity
    from_currency = Column(String(10), nullable=False, index=True)
    to_currency = Column(String(10), nullable=False, index=True)
    rate = Column(Numeric(16, 6), nullable=False)
    effective_date = Column(Date, default=func.current_date(), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

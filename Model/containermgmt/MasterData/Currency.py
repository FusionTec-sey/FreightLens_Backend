from sqlalchemy import Column, String, Integer, Boolean, DateTime, Date, Numeric, ForeignKey, func
from ...db import Base
from ...mixins import AuditMixin

# TABLE: List of currencies the system can use.
class Currency(Base):
    __tablename__ = 'currencies'
    __table_args__ = {'schema': 'containermgmt'}

    # code - VARCHAR(10), primary key.
    # ISO 4217 code, e.g. USD, SCR, EUR.
    code = Column(String(10), primary_key=True)  # ISO 4217 code, e.g. USD, SCR, EUR
    # name - VARCHAR(100), required.
    # Currency name.
    name = Column(String(100), nullable=False)
    # symbol - VARCHAR(10), optional.
    # Symbol shown with amounts.
    symbol = Column(String(10), nullable=True)
    # decimals - INTEGER, required, default 2.
    # Decimal places to show.
    decimals = Column(Integer, default=2, nullable=False)
    # is_active - BOOLEAN, required, default True.
    # False hides the record from use without deleting it.
    is_active = Column(Boolean, default=True, nullable=False)
    # created_at - TIMESTAMP WITH TIME ZONE, required.
    # When the row was created.
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # updated_at - TIMESTAMP WITH TIME ZONE, required.
    # When the row was last changed.
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


# TABLE: Exchange rates between currencies over time.
class CurrencyExchangeRate(AuditMixin, Base):
    __tablename__ = 'currency_exchange_rates'
    __table_args__ = {'schema': 'containermgmt'}

    # id - INTEGER, primary key.
    # Unique row number.
    id = Column(Integer, primary_key=True, autoincrement=True)
    # org_id - INTEGER, optional.
    # Company the rate belongs to (NULL = global standard rate).
    org_id = Column(Integer, nullable=True, index=True) # None indicates global standard rate, otherwise specific to entity
    # from_currency - VARCHAR(10), required.
    # Currency being converted from.
    from_currency = Column(String(10), nullable=False, index=True)
    # to_currency - VARCHAR(10), required.
    # Currency being converted to.
    to_currency = Column(String(10), nullable=False, index=True)
    # rate - NUMERIC(16,6), required.
    # Multiply the from-amount by this to get the to-amount.
    rate = Column(Numeric(16, 6), nullable=False)
    # effective_date - DATE, required.
    # Date from which the rate applies.
    effective_date = Column(Date, default=func.current_date(), nullable=False)
    # is_active - BOOLEAN, required, default True.
    # False hides the record from use without deleting it.
    is_active = Column(Boolean, default=True, nullable=False)

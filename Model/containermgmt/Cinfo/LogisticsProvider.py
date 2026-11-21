from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from ...db import Base  # Adjust the import based on your project structure

from ...mixins import AuditMixin

# TABLE: Shipping lines / logistics agents, with their free-day rules.
class LogisticsProvider(AuditMixin, Base):
    __tablename__ = "logisticsprovider"
    __table_args__ = {"schema": "containermgmt"}  # Remove or update if no schema used

    # Id - INTEGER, primary key.
    # Unique provider number.
    Id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Name - VARCHAR(45), optional.
    # Provider name.
    Name: Mapped[str] = mapped_column(String(45), nullable=True)
    # ExcludingDays - INTEGER, required, default 0.
    # Days excluded when counting free days (e.g. weekends/holidays).
    ExcludingDays: Mapped[int] = mapped_column(Integer, default=0)
    # FreeDays - INTEGER, required, default 0.
    # Default free days before demurrage charges start.
    FreeDays: Mapped[int] = mapped_column(Integer, default=0)
    
    bill_of_landings = relationship("BillOfLanding", back_populates="provider_rel")

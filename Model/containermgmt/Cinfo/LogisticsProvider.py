from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from ...db import Base  # Adjust the import based on your project structure

from ...mixins import AuditMixin

class LogisticsProvider(AuditMixin, Base):
    __tablename__ = "logisticsprovider"
    __table_args__ = {"schema": "containermgmt"}  # Remove or update if no schema used

    Id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    Name: Mapped[str] = mapped_column(String(45), nullable=True)
    ExcludingDays: Mapped[int] = mapped_column(Integer, default=0)
    FreeDays: Mapped[int] = mapped_column(Integer, default=0)
    
    bill_of_landings = relationship("BillOfLanding", back_populates="provider_rel")

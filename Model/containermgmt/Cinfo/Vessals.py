from datetime import date
from typing import List, Optional

from sqlalchemy import Integer, String, Date
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ...db import Base

from ...mixins import AuditMixin

class Vessal(AuditMixin, Base):
    __tablename__ = 'vessals'
    __table_args__ = {'schema': 'containermgmt'}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    VessalNo: Mapped[str] = mapped_column(String(45), nullable=False)
    
    bill_of_landings = relationship("BillOfLanding", back_populates="vessel_rel")
    # ArrivalOn: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    # containers: Mapped[List["ContainerDetails"]] = relationship( # type: ignore
    #     "ContainerDetails",
    #     back_populates="vessal",
    #     cascade="all, delete-orphan"
    # ) 

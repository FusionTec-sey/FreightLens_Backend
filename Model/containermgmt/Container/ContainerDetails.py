from datetime import datetime, date
from typing import Optional
from sqlalchemy import event

from sqlalchemy import Integer, String, Date, DateTime, Text, SmallInteger, ForeignKey, Column
from sqlalchemy.orm import Mapped, mapped_column, relationship
from ..Cinfo.ContainerMaterial import container_products
from ...db import Base  # Adjust path as needed
# from ..Container.BillOfLanding import BillOfLanding

class ContainerDetails(Base):
    __tablename__ = "container_details"
    __table_args__ = {"schema": "containermgmt"}  # Optional: Remove if no schema used

    Container_ID = Column(Integer, primary_key=True, autoincrement=True)
    container_no: Mapped[str] = mapped_column(String(50), nullable=False)

    # typ5e: Mapped[Optional[int]] = mapped_column(ForeignKey("containermgmt.container_type.type_id"), nullable=True)
    in_bound: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # emptied_at: Mapped[Optional[int]] = mapped_column(ForeignKey("containermgmt.unload_venue.venue_id"), nullable=True)
    empty_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    out_bound: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    unloaded_at_port: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # status: Mapped[Optional[int]] = mapped_column(ForeignKey("containermgmt.status.status_id"), nullable=True)
    tax: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    PONo: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)

    BillOfLanding = mapped_column(
        String(100), ForeignKey("containermgmt.bill_of_landing.BillOfLanding"), nullable=True
        )
    bill_of_landing = relationship("BillOfLanding", back_populates="containers", lazy="joined")
    
    status = mapped_column(Integer, ForeignKey("containermgmt.status.status_id"), nullable=True)
    status_rel = relationship("Status", lazy="joined")

    emptied_at = mapped_column(Integer, ForeignKey("containermgmt.unload_venue.venue_id"), nullable=True)
    emptied_at_rel = relationship("UnloadVenue", lazy="joined")

    type = mapped_column(Integer, ForeignKey("containermgmt.container_type.type_id"), nullable=True)
    type_rel = relationship("ContainerType", lazy="joined")
    
    materials = relationship(
        "Material",
        secondary=container_products,
        back_populates="containers"
    )
    
    documents = relationship(
        "ContainerDocs",
        back_populates="container",
        cascade="all, delete-orphan"
    )
    
    reports = relationship("ReportDetails", back_populates="container", cascade="all, delete-orphan")
    



@event.listens_for(ContainerDetails, "before_update")
def set_status_before_update(mapper, connection, target):
    """
    Replicates the MySQL trigger logic in SQLAlchemy ORM.
    """
    # ✅ Allow manual override from 2 → 3
    if target.status == 3 and target.__dict__.get("_orig_status") == 2:
        return  # skip overriding

    # ✅ Fetch arrival_date from related BillOfLanding
    arrival_date = None
    if target.bol:
        arrival_date = target.bol.ArrivalDate

    # ✅ Nested IF logic
    if target.out_bound is not None or target.unloaded_at_port is not None:
        target.status = 4
    elif target.empty_date is not None:
        target.status = 7
    elif target.in_bound is not None:
        target.status = 6
    elif arrival_date and arrival_date > date.today():
        target.status = 1
    elif arrival_date and arrival_date <= date.today():
        target.status = 2
    else:
        target.status = 8  # fallback


@event.listens_for(ContainerDetails, "before_insert")
def set_status_before_insert(mapper, connection, target):
    """
    Replicates the MySQL BEFORE INSERT trigger in SQLAlchemy ORM.
    """

    # ✅ Fetch arrival_date from related BillOfLanding
    arrival_date = None
    if target.bill_of_landing:
        arrival_date = target.bill_of_landing.ArrivalDate

    # ✅ Nested IF logic
    if target.out_bound is not None or target.unloaded_at_port is not None:
        target.status = 4  # Complete
    elif target.empty_date is not None:
        target.status = 7  # Empty
    elif target.in_bound is not None:
        target.status = 6  # Inbound
    elif arrival_date is None:
        target.status = 8  # Unknown/fallback
    elif arrival_date > date.today():
        target.status = 1  # In Transit
    else:
        target.status = 2  # On Port

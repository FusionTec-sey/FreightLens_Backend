from sqlalchemy import Column, String, Date, Text, DECIMAL, ForeignKey, Integer
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base

from ...db import Base

from ...mixins import AuditMixin

# TABLE: LEGACY: container damage report header.
class ReportDetails(AuditMixin, Base):
    __tablename__ = 'report_details'
    __table_args__ = {'schema': 'containermgmt'}

    # report_id - INTEGER, primary key.
    # Unique report number.
    report_id = Column(Integer, primary_key=True, autoincrement=True)
    # container_id - INTEGER, foreign key -> containermgmt.container_details.Container_ID, required.
    # Container this row refers to.
    container_id = Column(Integer, ForeignKey('containermgmt.container_details.Container_ID'), nullable=False)
    # report_date - DATE, required.
    # Date of the report.
    report_date = Column(Date, nullable=False)

    # Relationship to container
    container = relationship("ContainerDetails", back_populates="reports")
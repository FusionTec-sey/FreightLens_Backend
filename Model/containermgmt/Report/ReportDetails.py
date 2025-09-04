from sqlalchemy import Column, String, Date, Text, DECIMAL, ForeignKey, Integer
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base

from ...db import Base

class ReportDetails(Base):
    __tablename__ = 'report_details'
    __table_args__ = {'schema': 'containermgmt'}

    report_id = Column(Integer, primary_key=True, autoincrement=True)
    container_id = Column(Integer, ForeignKey('containermgmt.container_details.container_no'), nullable=False)
    report_date = Column(Date, nullable=False)

    # Relationship to container
    container = relationship("ContainerDetails", back_populates="reports")
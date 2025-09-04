from sqlalchemy import Column, String, Date, Text, DECIMAL, ForeignKey, Integer
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base

from ...db import Base

class DamageProduct(Base):
    __tablename__ = 'damageproduct'
    __table_args__ = {'schema': 'containermgmt'}

    id = Column(Integer, primary_key=True, autoincrement=True)
    report_id = Column(Integer, nullable=False)
    product_name = Column(String(45))
    qty = Column(String(45))
    note = Column(Text)

    images = relationship("ReportImage", back_populates="damage_product")
    # Optional: If report_id links to ReportDetails table
    # report = relationship("ReportDetails", back_populates="damage_products")
    # And in ReportDetails add: damage_products = relationship("DamageProduct", back_populates="report")

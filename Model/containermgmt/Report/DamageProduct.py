from sqlalchemy import Column, String, Date, Text, DECIMAL, ForeignKey, Integer
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base

from ...db import Base

from ...mixins import AuditMixin

# TABLE: LEGACY: damaged product lines in a container damage report.
class DamageProduct(AuditMixin, Base):
    __tablename__ = 'damageproduct'
    __table_args__ = {'schema': 'containermgmt'}

    # id - INTEGER, primary key.
    # Unique row number.
    id = Column(Integer, primary_key=True, autoincrement=True)
    # report_id - INTEGER, required.
    # Report this line belongs to.
    report_id = Column(Integer, nullable=False)
    # product_name - VARCHAR(45), optional.
    # Damaged product.
    product_name = Column(String(45))
    # qty - VARCHAR(45), optional.
    # Quantity damaged (text).
    qty = Column(String(45))
    # note - TEXT, optional.
    # Free-text remark.
    note = Column(Text)

    images = relationship("ReportImage", back_populates="damage_product")
    # Optional: If report_id links to ReportDetails table
    # report = relationship("ReportDetails", back_populates="damage_products")
    # And in ReportDetails add: damage_products = relationship("DamageProduct", back_populates="report")

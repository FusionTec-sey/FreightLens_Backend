
from sqlalchemy import Column, String,Integer
from sqlalchemy.orm import relationship
from ...db import Base
# from Model.db import Base
from ...mixins import AuditMixin

class Supplier(AuditMixin, Base):
    __tablename__ = 'supplier'
    __table_args__ = {'schema': 'containermgmt'}

    supplier_id = Column(Integer, primary_key=True)
    name = Column(String(45))
    address = Column(String(45))
    email = Column(String(45))
    
    bill_of_landings = relationship("BillOfLanding", back_populates="supplier_rel")

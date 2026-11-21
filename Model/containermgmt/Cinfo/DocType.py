
from sqlalchemy import Column, String,Integer
from sqlalchemy.orm import relationship
from ...db import Base

from ...mixins import AuditMixin

# TABLE: Lookup list of shipping document kinds.
class ShippingDocument(AuditMixin, Base):
    __tablename__ = 'shipping_document'
    __table_args__ = {'schema': 'containermgmt'}

    # doc_id - INTEGER, primary key.
    # Unique document-type number.
    doc_id = Column(Integer, primary_key=True)
    # doc_type - VARCHAR(45), optional.
    # Document-type name.
    doc_type = Column(String(45))
    
    bill_of_landings = relationship("BillOfLanding", back_populates="doc_rel")
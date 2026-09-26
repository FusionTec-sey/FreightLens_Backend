from sqlalchemy import Column, String, Integer, Boolean, Text, JSON
from ...db import Base
from ...mixins import AuditMixin

class MasterDocumentType(AuditMixin, Base):
    __tablename__ = 'master_document_types'
    __table_args__ = {'schema': 'containermgmt'}

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(50), unique=True, nullable=False, index=True) # e.g. quotation, payment_proof, bill_of_lading
    name = Column(String(100), nullable=False)                         # e.g. Vendor Quotation, Bank Swift Slip
    description = Column(Text, nullable=True)
    applicable_spaces = Column(JSON, nullable=False, default=list)    # ["SOURCING", "ORDER", "PAYMENT", "SHIPPING", "DEFECTS"]
    is_active = Column(Boolean, default=True, nullable=False)
    display_order = Column(Integer, default=0, nullable=False)

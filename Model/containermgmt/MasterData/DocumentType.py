from sqlalchemy import Boolean, Column, Integer, JSON, String, Text, UniqueConstraint
from ...db import Base
from ...mixins import AuditMixin, OrgMixin

class MasterDocumentType(OrgMixin, AuditMixin, Base):
    __tablename__ = 'master_document_types'
    __table_args__ = (
        UniqueConstraint("org_id", "code", name="uq_master_document_types_org_code"),
        {'schema': 'containermgmt'},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(50), nullable=False, index=True) # e.g. quotation, payment_proof, bill_of_lading
    is_shared = Column(Boolean, default=False, nullable=False, index=True)
    name = Column(String(100), nullable=False)                         # e.g. Vendor Quotation, Bank Swift Slip
    description = Column(Text, nullable=True)
    applicable_spaces = Column(JSON, nullable=False, default=list)    # ["SOURCING", "ORDER", "PAYMENT", "SHIPPING", "DEFECTS"]
    is_active = Column(Boolean, default=True, nullable=False)
    display_order = Column(Integer, default=0, nullable=False)

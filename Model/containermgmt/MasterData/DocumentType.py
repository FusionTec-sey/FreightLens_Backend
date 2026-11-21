from sqlalchemy import Boolean, Column, Integer, JSON, String, Text, UniqueConstraint
from ...db import Base
from ...mixins import AuditMixin, OrgMixin

# TABLE: Kinds of documents users can upload (quotation, payment proof, B/L...).
class MasterDocumentType(OrgMixin, AuditMixin, Base):
    __tablename__ = 'master_document_types'
    __table_args__ = (
        UniqueConstraint("org_id", "code", name="uq_master_document_types_org_code"),
        {'schema': 'containermgmt'},
    )

    # id - INTEGER, primary key.
    # Unique row number.
    id = Column(Integer, primary_key=True, autoincrement=True)
    # code - VARCHAR(50), required.
    # Short code, unique per company.
    code = Column(String(50), nullable=False, index=True) # e.g. quotation, payment_proof, bill_of_lading
    # is_shared - BOOLEAN, required, default False.
    # True = visible to every company, not only the owning one.
    is_shared = Column(Boolean, default=False, nullable=False, index=True)
    # name - VARCHAR(100), required.
    # Name shown in the upload list.
    name = Column(String(100), nullable=False)                         # e.g. Vendor Quotation, Bank Swift Slip
    # description - TEXT, optional.
    # Free-text description.
    description = Column(Text, nullable=True)
    # applicable_spaces - JSON, required.
    # Screens where it is offered: SOURCING, ORDER, PAYMENT, SHIPPING, DEFECTS (JSON list).
    applicable_spaces = Column(JSON, nullable=False, default=list)    # ["SOURCING", "ORDER", "PAYMENT", "SHIPPING", "DEFECTS"]
    # is_active - BOOLEAN, required, default True.
    # False hides the record from use without deleting it.
    is_active = Column(Boolean, default=True, nullable=False)
    # display_order - INTEGER, required, default 0.
    # Order in the list.
    display_order = Column(Integer, default=0, nullable=False)

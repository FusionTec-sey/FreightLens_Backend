from sqlalchemy import Column, DateTime, String, Integer, Numeric, Boolean, Text, ForeignKey
from sqlalchemy.orm import relationship
from ...db import Base
from ...mixins import AuditMixin
from ..MasterData.PaymentTerm import PaymentTerm

class Supplier(AuditMixin, Base):
    __tablename__ = 'supplier'
    __table_args__ = {'schema': 'containermgmt'}

    supplier_id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("usercredentials.organisations.id"), nullable=False, index=True)
    is_shared = Column(Boolean, default=False, nullable=False, index=True)
    name = Column(String(255))
    code = Column(String(50), nullable=True)
    address = Column(String(255), nullable=True)
    email = Column(String(100), nullable=True)
    phone = Column(String(50), nullable=True)
    contact_person = Column(String(100), nullable=True)
    country = Column(String(100), nullable=True)
    logo_url = Column(String(500), nullable=True)
    default_currency = Column(String(10), default="USD", nullable=True)
    default_payment_term_id = Column(Integer, ForeignKey("containermgmt.payment_terms.id", ondelete="SET NULL"), nullable=True)
    variance_threshold_pct = Column(Numeric(5, 2), default=2.0, nullable=True)
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    # The counterparty seam. A vendor who runs FreightLens themselves will one
    # day be linked here by consent; nothing reads it yet. See
    # docs/planning/CONNECTED-VENDOR-NETWORK-FUTURE-SCOPE.md.
    linked_org_id = Column(
        Integer,
        ForeignKey("usercredentials.organisations.id", ondelete="SET NULL"),
        nullable=True,
    )

    
    bill_of_landings = relationship("BillOfLanding", back_populates="supplier_rel")
    payment_term = relationship("PaymentTerm", foreign_keys=[default_payment_term_id], lazy="joined")
    organisation = relationship("Organisation", foreign_keys=[org_id], viewonly=True)
    identifiers = relationship(
        "SupplierIdentifier", back_populates="supplier",
        cascade="all, delete-orphan", passive_deletes=True,
    )


class SupplierIdentifier(AuditMixin, Base):
    """What proves a supplier is who they say they are, one claim per row.

    A tax number, a company registration number, later a GLN or a DUNS. Rows
    rather than columns because the set differs by country and no single one can
    be made mandatory -- and because country plus registration number is a far
    stronger duplicate check than a similar name.
    """
    __tablename__ = 'supplier_identifiers'
    __table_args__ = {'schema': 'containermgmt'}

    id = Column(Integer, primary_key=True)
    supplier_id = Column(
        Integer,
        ForeignKey("containermgmt.supplier.supplier_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    id_type = Column(String(30), nullable=False)   # TAX, VAT, REGISTRATION, GLN, DUNS, LEI
    country = Column(String(100), nullable=True)
    value = Column(String(100), nullable=False)
    is_primary = Column(Boolean, default=False, nullable=False)
    # Set only when someone checked the number against a register. An
    # identifier proves nothing until then, which is the whole point of
    # recording when it happened and who did it.
    verified_at = Column(DateTime(timezone=True), nullable=True)
    verified_by = Column(Integer, ForeignKey("usercredentials.users.id"), nullable=True)
    notes = Column(Text, nullable=True)

    supplier = relationship("Supplier", back_populates="identifiers")


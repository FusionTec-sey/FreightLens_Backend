from sqlalchemy import Column, DateTime, String, Integer, Numeric, Boolean, Text, ForeignKey
from sqlalchemy.orm import relationship
from ...db import Base
from ...mixins import AuditMixin
from ..MasterData.PaymentTerm import PaymentTerm

# TABLE: Vendor master: the companies we buy from.
class Supplier(AuditMixin, Base):
    __tablename__ = 'supplier'
    __table_args__ = {'schema': 'containermgmt'}

    # supplier_id - INTEGER, primary key.
    # Unique vendor number.
    supplier_id = Column(Integer, primary_key=True)
    # org_id - INTEGER, foreign key -> usercredentials.organisations.id, required.
    # Company that created the vendor.
    org_id = Column(Integer, ForeignKey("usercredentials.organisations.id"), nullable=False, index=True)
    # is_shared - BOOLEAN, required, default False.
    # True = visible to every company, not only the owning one.
    is_shared = Column(Boolean, default=False, nullable=False, index=True)
    # name - VARCHAR(255), optional.
    # Vendor name.
    name = Column(String(255))
    # code - VARCHAR(50), optional.
    # Short vendor code.
    code = Column(String(50), nullable=True)
    # address - VARCHAR(255), optional.
    # Main address in one line (legacy single field).
    address = Column(String(255), nullable=True)
    # email - VARCHAR(100), optional.
    # Main e-mail (mirrors the primary contact).
    email = Column(String(100), nullable=True)
    # phone - VARCHAR(50), optional.
    # Main phone (mirrors the primary contact).
    phone = Column(String(50), nullable=True)
    # contact_person - VARCHAR(100), optional.
    # Main contact name (mirrors the primary contact).
    contact_person = Column(String(100), nullable=True)
    # country - VARCHAR(100), optional.
    # Vendor's country.
    country = Column(String(100), nullable=True)
    # logo_url - VARCHAR(500), optional.
    # Vendor logo image location.
    logo_url = Column(String(500), nullable=True)
    # default_currency - VARCHAR(10), optional, default USD.
    # Currency normally used when buying from this vendor.
    default_currency = Column(String(10), default="USD", nullable=True)
    # default_payment_term_id - INTEGER, foreign key -> containermgmt.payment_terms.id, optional.
    # Payment terms normally agreed with this vendor.
    default_payment_term_id = Column(Integer, ForeignKey("containermgmt.payment_terms.id", ondelete="SET NULL"), nullable=True)
    # variance_threshold_pct - NUMERIC(5,2), optional, default 2.0.
    # Allowed % difference between PO price and vendor proforma before approval is needed (default 2).
    variance_threshold_pct = Column(Numeric(5, 2), default=2.0, nullable=True)
    # notes - TEXT, optional.
    # Internal remarks about the vendor.
    notes = Column(Text, nullable=True)
    # is_active - BOOLEAN, required, default True.
    # False = vendor no longer used.
    is_active = Column(Boolean, default=True, nullable=False)

    # The counterparty seam. A vendor who runs FreightLens themselves will one
    # day be linked here by consent; nothing reads it yet. See
    # docs/planning/CONNECTED-VENDOR-NETWORK-FUTURE-SCOPE.md.
    # linked_org_id - INTEGER, foreign key -> usercredentials.organisations.id, optional.
    # Reserved: company account of the vendor if they also run the system (future feature, not read
    # yet).
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
    contacts = relationship(
        "SupplierContact", back_populates="supplier",
        cascade="all, delete-orphan", passive_deletes=True,
    )
    addresses = relationship(
        "SupplierAddress", back_populates="supplier",
        cascade="all, delete-orphan", passive_deletes=True,
    )


# TABLE: Proof of a vendor's identity (tax, VAT, registration numbers), one claim per row.
class SupplierIdentifier(AuditMixin, Base):
    """What proves a supplier is who they say they are, one claim per row.

    A tax number, a company registration number, later a GLN or a DUNS. Rows
    rather than columns because the set differs by country and no single one can
    be made mandatory -- and because country plus registration number is a far
    stronger duplicate check than a similar name.
    """
    __tablename__ = 'supplier_identifiers'
    __table_args__ = {'schema': 'containermgmt'}

    # id - INTEGER, primary key.
    # Unique row number.
    id = Column(Integer, primary_key=True)
    # supplier_id - INTEGER, foreign key -> containermgmt.supplier.supplier_id, required.
    # Vendor the identifier belongs to.
    supplier_id = Column(
        Integer,
        ForeignKey("containermgmt.supplier.supplier_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # id_type - VARCHAR(30), required.
    # TAX, VAT, REGISTRATION, GLN, DUNS or LEI.
    id_type = Column(String(30), nullable=False)   # TAX, VAT, REGISTRATION, GLN, DUNS, LEI
    # country - VARCHAR(100), optional.
    # Country that issued the identifier.
    country = Column(String(100), nullable=True)
    # value - VARCHAR(100), required.
    # The identifier number itself (country + number is a strong duplicate check).
    value = Column(String(100), nullable=False)
    # is_primary - BOOLEAN, required, default False.
    # True marks the main/default row among several for the same parent.
    is_primary = Column(Boolean, default=False, nullable=False)
    # Set only when someone checked the number against a register. An
    # identifier proves nothing until then, which is the whole point of
    # recording when it happened and who did it.
    # verified_at - TIMESTAMP WITH TIME ZONE, optional.
    # When someone checked it against an official register (NULL = unverified).
    verified_at = Column(DateTime(timezone=True), nullable=True)
    # verified_by - INTEGER, foreign key -> usercredentials.users.id, optional.
    # User who verified it.
    verified_by = Column(Integer, ForeignKey("usercredentials.users.id"), nullable=True)
    # notes - TEXT, optional.
    # Free-text remarks.
    notes = Column(Text, nullable=True)

    supplier = relationship("Supplier", back_populates="identifiers")


# TABLE: People at the vendor, each with what they are the contact for.
class SupplierContact(AuditMixin, Base):
    """A person at the vendor, with what they are the person for.

    The supplier row has one contact_person, one email and one phone. A vendor
    has a salesperson, someone in accounts and someone who answers about a late
    shipment, and in one field the second of them overwrites the first. The
    primary row is what the old single fields keep showing, so nothing that
    reads them changes.
    """
    __tablename__ = 'supplier_contacts'
    __table_args__ = {'schema': 'containermgmt'}

    # id - INTEGER, primary key.
    # Unique row number.
    id = Column(Integer, primary_key=True)
    # supplier_id - INTEGER, foreign key -> containermgmt.supplier.supplier_id, required.
    # Vendor this row refers to (supplier table).
    supplier_id = Column(
        Integer,
        ForeignKey("containermgmt.supplier.supplier_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # name - VARCHAR(150), required.
    # Contact person's name.
    name = Column(String(150), nullable=False)
    # role - VARCHAR(30), optional.
    # SALES, ACCOUNTS, LOGISTICS, ESCALATION or OTHER.
    role = Column(String(30), nullable=True)       # SALES, ACCOUNTS, LOGISTICS, ESCALATION, OTHER
    # job_title - VARCHAR(100), optional.
    # Contact's job title.
    job_title = Column(String(100), nullable=True)
    # email - VARCHAR(150), optional.
    # Contact e-mail.
    email = Column(String(150), nullable=True)
    # phone - VARCHAR(50), optional.
    # Contact office phone.
    phone = Column(String(50), nullable=True)
    # mobile - VARCHAR(50), optional.
    # Contact mobile number.
    mobile = Column(String(50), nullable=True)
    # is_primary - BOOLEAN, required, default False.
    # True marks the main/default row among several for the same parent.
    is_primary = Column(Boolean, default=False, nullable=False)
    # notes - TEXT, optional.
    # Free-text remarks.
    notes = Column(Text, nullable=True)

    supplier = relationship("Supplier", back_populates="contacts")


# TABLE: Places the vendor has (registered office, factory, warehouse, remit-to).
class SupplierAddress(AuditMixin, Base):
    """A place the vendor has, with what it is for.

    A registered office is not the factory, the factory is not the warehouse
    goods ship from, and none of them is where a payment advice should go. Each
    is a different mistake on a different document, so each is its own row with
    its own type.
    """
    __tablename__ = 'supplier_addresses'
    __table_args__ = {'schema': 'containermgmt'}

    # id - INTEGER, primary key.
    # Unique row number.
    id = Column(Integer, primary_key=True)
    # supplier_id - INTEGER, foreign key -> containermgmt.supplier.supplier_id, required.
    # Vendor this row refers to (supplier table).
    supplier_id = Column(
        Integer,
        ForeignKey("containermgmt.supplier.supplier_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # address_type - VARCHAR(30), required, default OTHER.
    # REGISTERED, FACTORY, WAREHOUSE, REMIT_TO or OTHER.
    address_type = Column(String(30), nullable=False, default="OTHER")  # REGISTERED, FACTORY, WAREHOUSE, REMIT_TO, OTHER
    # label - VARCHAR(100), optional.
    # Short name for this address.
    label = Column(String(100), nullable=True)
    # line1 - VARCHAR(200), optional.
    # Address line 1.
    line1 = Column(String(200), nullable=True)
    # line2 - VARCHAR(200), optional.
    # Address line 2.
    line2 = Column(String(200), nullable=True)
    # city - VARCHAR(100), optional.
    # City.
    city = Column(String(100), nullable=True)
    # state - VARCHAR(100), optional.
    # State/province.
    state = Column(String(100), nullable=True)
    # postal_code - VARCHAR(30), optional.
    # Postal/ZIP code.
    postal_code = Column(String(30), nullable=True)
    # country - VARCHAR(100), optional.
    # Country.
    country = Column(String(100), nullable=True)
    # is_primary - BOOLEAN, required, default False.
    # True marks the main/default row among several for the same parent.
    is_primary = Column(Boolean, default=False, nullable=False)
    # notes - TEXT, optional.
    # Free-text remarks.
    notes = Column(Text, nullable=True)

    supplier = relationship("Supplier", back_populates="addresses")

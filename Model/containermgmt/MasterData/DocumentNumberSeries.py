from sqlalchemy import Boolean, Column, Date, Integer, String, UniqueConstraint, text
from ...db import Base
from ...mixins import AuditMixin, OrgMixin


class DocumentNumberSeries(OrgMixin, AuditMixin, Base):
    """How one company numbers one kind of document.

    Each of the six document types used to build its own number from a literal
    in Python, none of them aware of the company the document belonged to. One
    row here replaces one of those formats, so an administrator can set the
    prefix, the number to continue from and when the counter resets.

    `next_number` is the number the next document will take. It is allocated
    under a row lock rather than derived by counting rows: counting meant that
    deleting a document handed its number to the next one, and that two people
    creating a document at the same moment were issued the same number.

    A company with no row here, or with `is_active` false, keeps the old
    hardcoded format, so this can be switched on one company at a time.
    """

    __tablename__ = "document_number_series"
    __table_args__ = (
        UniqueConstraint("org_id", "doc_type", name="uq_document_number_series_org_doc"),
        {"schema": "containermgmt"},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    # PO, RFQ, REQ, GRN, PL, DEF
    doc_type = Column(String(30), nullable=False, index=True)

    prefix = Column(String(30), nullable=False, default="", server_default=text("''"))
    suffix = Column(String(30), nullable=False, default="", server_default=text("''"))
    padding = Column(Integer, nullable=False, default=4, server_default=text("4"))
    next_number = Column(Integer, nullable=False, default=1, server_default=text("1"))

    # never, yearly, monthly
    reset_policy = Column(String(10), nullable=False, default="never", server_default=text("'never'"))
    # strftime-style token inserted between prefix and counter, e.g. %y%m%d
    date_token = Column(String(20), nullable=True)
    # So a yearly reset happens once in the period, not on every allocation.
    last_reset_on = Column(Date, nullable=True)

    is_active = Column(Boolean, nullable=False, default=False, server_default=text("false"))

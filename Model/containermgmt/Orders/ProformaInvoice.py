from sqlalchemy import Column, Integer, String, Text, Date, ForeignKey, Numeric, JSON
from sqlalchemy.orm import relationship
from ...db import Base
from ...mixins import AuditMixin, OrgMixin


# TABLE: Vendor's proforma invoice for one PO - the document payments are made against.
class ProformaInvoice(OrgMixin, AuditMixin, Base):
    """The vendor's proforma invoice against one purchase order.

    The PO is the commitment and carries no money. The proforma is the document
    the vendor asks to be paid against, so every payment is recorded on it
    (order_payments.proforma_id) and the PO's advance/balance/status are
    mirrored from the proformas by Services.proforma_service.

    Status: RECEIVED -> APPROVED -> PART_PAID -> PAID, or SUPERSEDED when a
    revised proforma replaces it, or CANCELLED. The paid states are derived
    from the payments and never typed in.
    """
    __tablename__ = "proforma_invoices"
    __table_args__ = {'schema': 'containermgmt'}

    # id - INTEGER, primary key.
    # Unique row number.
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    # proforma_number - VARCHAR(100), required, unique.
    # Our own reference number (unique).
    proforma_number = Column(String(100), nullable=False, unique=True, index=True)  # our reference
    # vendor_proforma_number - VARCHAR(100), optional.
    # Number the vendor gave it.
    vendor_proforma_number = Column(String(100), nullable=True)                      # the vendor's own
    # vendor_proforma_date - DATE, optional.
    # Date on the vendor's document.
    vendor_proforma_date = Column(Date, nullable=True)
    # valid_until - DATE, optional.
    # Date the proforma expires.
    valid_until = Column(Date, nullable=True)

    # po_id - INTEGER, foreign key -> containermgmt.purchase_orders.id, required.
    # Purchase order (or RFQ) this row belongs to.
    po_id = Column(Integer, ForeignKey("containermgmt.purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    # supplier_id - INTEGER, foreign key -> containermgmt.supplier.supplier_id, optional.
    # Vendor this row refers to (supplier table).
    supplier_id = Column(Integer, ForeignKey("containermgmt.supplier.supplier_id"), nullable=True)
    # The vendor as it stood when the proforma was recorded; see PurchaseOrder.
    # supplier_name_at_issue - VARCHAR(255), optional.
    # Vendor name frozen when recorded.
    supplier_name_at_issue = Column(String(255), nullable=True)

    # currency - VARCHAR(10), optional, default USD.
    # Currency code of the amounts on this row (e.g. USD, SCR).
    currency = Column(String(10), default="USD")
    # exchange_rate_to_base - NUMERIC(18,8), optional.
    # Rate used to convert the document currency into the base currency.
    exchange_rate_to_base = Column(Numeric(18, 8), nullable=True)
    # total_amount - NUMERIC(14,2), required, default 0.
    # Invoice total.
    total_amount = Column(Numeric(14, 2), nullable=False, default=0)
    # advance_percent - NUMERIC(5,2), optional.
    # % payable in advance.
    advance_percent = Column(Numeric(5, 2), nullable=True)
    # payment_terms - VARCHAR(255), optional.
    # Payment terms text.
    payment_terms = Column(String(255), nullable=True)
    # bank_details - JSON, optional.
    # Where to pay, as written by the vendor (JSON snapshot).
    bank_details = Column(JSON, nullable=True)  # snapshot of where to pay, as the vendor wrote it

    # status - VARCHAR(30), required, default RECEIVED.
    # RECEIVED, APPROVED, PART_PAID, PAID, SUPERSEDED or CANCELLED (paid states are derived from
    # payments).
    status = Column(String(30), nullable=False, default="RECEIVED", index=True)
    # VENDOR = a document the vendor sent; MIGRATED = made to carry payments
    # that were recorded on the PO before proformas existed.
    # source - VARCHAR(20), required, default VENDOR.
    # VENDOR (sent by vendor) or MIGRATED (created for old PO payments).
    source = Column(String(20), nullable=False, default="VENDOR")
    # supersedes_id - INTEGER, foreign key -> containermgmt.proforma_invoices.id, optional.
    # Earlier proforma this one replaces.
    supersedes_id = Column(Integer, ForeignKey("containermgmt.proforma_invoices.id", ondelete="SET NULL"), nullable=True)

    # NONE (no PO price to compare), WITHIN, EXCEEDED (needs Approve_Variance), APPROVED
    # variance_status - VARCHAR(20), required, default NONE.
    # NONE, WITHIN, EXCEEDED (needs Approve_Variance) or APPROVED.
    variance_status = Column(String(20), nullable=False, default="NONE")
    # variance_data - JSON, optional.
    # Price differences vs the PO (JSON).
    variance_data = Column(JSON, nullable=True)
    # variance_justification - TEXT, optional.
    # Reason given for accepting a variance.
    variance_justification = Column(Text, nullable=True)

    # approved_by - INTEGER, optional.
    # User who approved the variance.
    approved_by = Column(Integer, nullable=True)
    # approved_at - DATE, optional.
    # Date approved.
    approved_at = Column(Date, nullable=True)
    # notes - TEXT, optional.
    # Free-text remarks.
    notes = Column(Text, nullable=True)

    # Each revision is asked for a reason first and recorded here, newest last:
    # {"at", "by", "reason", "summary"}.
    # revision_count - INTEGER, required, default 0.
    # How many times this record has been revised.
    revision_count = Column(Integer, nullable=False, default=0)
    # revisions - JSON, optional.
    # Reasons for each revision: {at, by, reason, summary}.
    revisions = Column(JSON, nullable=True)

    purchase_order = relationship("PurchaseOrder", back_populates="proformas", foreign_keys=[po_id])
    supplier_rel = relationship("Supplier", foreign_keys=[supplier_id])
    items = relationship("ProformaInvoiceItem", back_populates="proforma", cascade="all, delete-orphan",
                         order_by="ProformaInvoiceItem.id")
    payments = relationship("OrderPayment", back_populates="proforma", foreign_keys="OrderPayment.proforma_id")


# TABLE: Lines of a proforma invoice, compared with the PO price.
class ProformaInvoiceItem(OrgMixin, AuditMixin, Base):
    __tablename__ = "proforma_invoice_items"
    __table_args__ = {'schema': 'containermgmt'}

    # id - INTEGER, primary key.
    # Unique row number.
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    # proforma_id - INTEGER, foreign key -> containermgmt.proforma_invoices.id, required.
    # Proforma this line belongs to.
    proforma_id = Column(Integer, ForeignKey("containermgmt.proforma_invoices.id", ondelete="CASCADE"), nullable=False, index=True)
    # po_item_id - INTEGER, foreign key -> containermgmt.po_items.id, optional.
    # PO line it corresponds to.
    po_item_id = Column(Integer, ForeignKey("containermgmt.po_items.id", ondelete="SET NULL"), nullable=True, index=True)

    # item_code - VARCHAR(100), optional.
    # Item/article code for this line.
    item_code = Column(String(100), nullable=True)
    # description - TEXT, required.
    # Free-text description.
    description = Column(Text, nullable=False)
    # quantity - NUMERIC(12,2), required, default 1.
    # Quantity invoiced.
    quantity = Column(Numeric(12, 2), nullable=False, default=1)
    # unit - VARCHAR(50), optional, default PCS.
    # Unit of measure, e.g. PCS, KG.
    unit = Column(String(50), default="PCS")
    # unit_price - NUMERIC(14,2), required, default 0.
    # Vendor's unit price.
    unit_price = Column(Numeric(14, 2), nullable=False, default=0)
    # total_price - NUMERIC(14,2), required, default 0.
    # Line total.
    total_price = Column(Numeric(14, 2), nullable=False, default=0)

    # The PO line's price at the time, and how far the vendor's differs.
    # po_unit_price - NUMERIC(14,2), optional.
    # PO line price at that time.
    po_unit_price = Column(Numeric(14, 2), nullable=True)
    # variance_pct - NUMERIC(8,2), optional.
    # % difference between vendor price and PO price.
    variance_pct = Column(Numeric(8, 2), nullable=True)

    proforma = relationship("ProformaInvoice", back_populates="items")
    po_item = relationship("POItem", foreign_keys=[po_item_id])

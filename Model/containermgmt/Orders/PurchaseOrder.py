from sqlalchemy import Column, Integer, String, Boolean, Date, Text, ForeignKey, JSON, Numeric
from sqlalchemy.orm import relationship
from ...db import Base
from ...mixins import AuditMixin, OrgMixin

# TABLE: Central procurement document: one row is either an RFQ (request for quotes) or a PO (binding
#        order).
class PurchaseOrder(OrgMixin, AuditMixin, Base):
    __tablename__ = "purchase_orders"
    __table_args__ = {'schema': 'containermgmt'}

    # id - INTEGER, primary key.
    # Unique row number.
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    # po_number - VARCHAR(100), required, unique.
    # Unique document number.
    po_number = Column(String(100), nullable=False, unique=True, index=True)
    # po_nce - VARCHAR(100), optional.
    # Internal accounts reference (NPO).
    po_nce = Column(String(100), nullable=True)  # PO Reference (Internal Accounts Reference / NPO)
    
    # Document classification & lineage: RFQ (pre-award) vs PO (binding order)
    # doc_type - VARCHAR(20), required, default PO.
    # RFQ or PO.
    doc_type = Column(String(20), nullable=False, default="PO", index=True)  # "RFQ" or "PO"
    # parent_rfq_id - INTEGER, foreign key -> containermgmt.purchase_orders.id, optional.
    # RFQ this PO was created from.
    parent_rfq_id = Column(Integer, ForeignKey("containermgmt.purchase_orders.id", ondelete="SET NULL"), nullable=True, index=True)
    # origin_rfq_number - VARCHAR(100), optional.
    # Number of the originating RFQ, e.g. RFQ-2026-0042.
    origin_rfq_number = Column(String(100), nullable=True)  # e.g. "RFQ-2026-0042"
    # split_index - VARCHAR(10), optional.
    # Letter (A, B, C) when one RFQ is split across vendors.
    split_index = Column(String(10), nullable=True)  # "A", "B", "C", etc.

    # RFQ = reached through quotes and award; DIRECT = a confirmed RFQ converted
    # straight to a PO with no quote round.
    # order_source - VARCHAR(20), required, default RFQ.
    # RFQ (through quotes and award) or DIRECT (confirmed RFQ converted straight to PO).
    order_source = Column(String(20), nullable=False, default="RFQ", server_default="RFQ", index=True)
    # The template an RFQ was made from. An RFQ carries no vendor while it is a
    # sourcing document, so this is how conversion finds the template's vendor.
    # source_template_id - INTEGER, foreign key -> containermgmt.order_templates.id, optional.
    # Order template the RFQ was made from.
    source_template_id = Column(Integer, ForeignKey("containermgmt.order_templates.id", ondelete="SET NULL"), nullable=True, index=True)

    # Store request link
    # request_id - INTEGER, foreign key -> containermgmt.store_requests.id, optional.
    # Store request that triggered it.
    request_id = Column(Integer, ForeignKey("containermgmt.store_requests.id"), nullable=True, index=True)
    
    # supplier_id - INTEGER, foreign key -> containermgmt.supplier.supplier_id, optional.
    # Vendor this row refers to (supplier table).
    supplier_id = Column(Integer, ForeignKey("containermgmt.supplier.supplier_id"), nullable=True)
    # company - VARCHAR(255), optional.
    # Vendor company name text (fallback).
    company = Column(String(255), nullable=True)  # Supplier company name fallback
    # The vendor as it stood when this order was raised. A vendor is shared and
    # editable, so resolving its name live meant renaming it rewrote every
    # historical order and every reprint. These are written once and not
    # revisited, so a correction reaches new documents only.
    # supplier_name_at_issue - VARCHAR(255), optional.
    # Vendor name frozen when the order was raised, so later renames do not alter history.
    supplier_name_at_issue = Column(String(255), nullable=True)
    # supplier_address_at_issue - VARCHAR(500), optional.
    # Vendor address frozen when the order was raised.
    supplier_address_at_issue = Column(String(500), nullable=True)
    # goods_description - TEXT, optional.
    # Summary of the goods.
    goods_description = Column(Text, nullable=True)
    # material_ids - JSON, optional.
    # Selected material ids (JSON list).
    material_ids = Column(JSON, nullable=True)  # List of selected material IDs

    # Main Lifecycle Status (references order_status table)
    # status_id - INTEGER, foreign key -> containermgmt.order_status.id, optional.
    # Link to the order_status lookup.
    status_id = Column(Integer, ForeignKey("containermgmt.order_status.id"), nullable=True)
    # status - VARCHAR(50), optional, default DRAFT.
    # Main status: DRAFT, SUBMITTED, SOURCING, ORDERED...
    status = Column(String(50), default="DRAFT", index=True)  # DRAFT, SUBMITTED, SOURCING, ORDERED, etc.
    # status_label - VARCHAR(100), optional, default Draft.
    # Readable status text.
    status_label = Column(String(100), default="Draft")

    # ── Procurement Lifecycle Stage (7-stage pipeline) ───────────────────
    # DRAFT -> CONFIRMED -> RFQ_SENT -> QUOTE_RECEIVED -> QUOTE_APPROVED -> PO_ISSUED -> PROFORMA
    # lifecycle_stage - VARCHAR(30), required, default DRAFT.
    # Pipeline stage: DRAFT, CONFIRMED, RFQ_SENT, QUOTE_RECEIVED, QUOTE_APPROVED, PO_ISSUED, PROFORMA.
    lifecycle_stage = Column(String(30), nullable=False, default="DRAFT", index=True)
    # stage_version - INTEGER, required, default 1.
    # Revision number within the current stage.
    stage_version = Column(Integer, nullable=False, default=1) # Version within current stage (e.g., Draft v1, Draft v2, Confirmed v1)
    # lifecycle_version - INTEGER, required, default 1.
    # Sequential concurrency counter.
    lifecycle_version = Column(Integer, nullable=False, default=1) # Sequential concurrency counter
    # lifecycle_locked - BOOLEAN, required, default False.
    # True = editing is locked.
    lifecycle_locked = Column(Boolean, nullable=False, default=False)
    # selected_quote_id - INTEGER, foreign key -> containermgmt.vendor_quotes.id, optional.
    # Winning vendor quote.
    selected_quote_id = Column(Integer, ForeignKey("containermgmt.vendor_quotes.id", ondelete="SET NULL"), nullable=True)

    # Distinct Tracking Dimensions (preventing single-remark overload)
    # payment_status - VARCHAR(50), optional, default NONE.
    # NONE, ADVANCE_PAID, PART_PAID or FULLY_PAID.
    payment_status = Column(String(50), default="NONE")       # NONE, ADVANCE_PAID, PART_PAID, FULLY_PAID
    # production_status - VARCHAR(50), optional, default NOT_STARTED.
    # NOT_STARTED, IN_PRODUCTION or READY.
    production_status = Column(String(50), default="NOT_STARTED") # NOT_STARTED, IN_PRODUCTION, READY
    # shipment_status - VARCHAR(50), optional, default NOT_SHIPPED.
    # NOT_SHIPPED, PARTIALLY_SHIPPED, SHIPPED or ARRIVED.
    shipment_status = Column(String(50), default="NOT_SHIPPED")   # NOT_SHIPPED, PARTIALLY_SHIPPED, SHIPPED, ARRIVED
    # receipt_status - VARCHAR(50), optional, default PENDING.
    # PENDING, PARTIALLY_RECEIVED or RECEIVED.
    receipt_status = Column(String(50), default="PENDING")        # PENDING, PARTIALLY_RECEIVED, RECEIVED

    # Financial details (confidential - visible to Accounts/Management)
    # total_amount - NUMERIC(14,2), optional.
    # Order total (confidential - Accounts/Management).
    total_amount = Column(Numeric(14, 2), nullable=True)
    # advance_amount - NUMERIC(14,2), optional.
    # Advance payment amount.
    advance_amount = Column(Numeric(14, 2), nullable=True)
    # balance_amount - NUMERIC(14,2), optional.
    # Balance still to pay.
    balance_amount = Column(Numeric(14, 2), nullable=True)
    # currency - VARCHAR(10), optional, default USD.
    # Currency code of the amounts on this row (e.g. USD, SCR).
    currency = Column(String(10), default="USD")
    # base_currency - VARCHAR(10), optional.
    # Company reporting currency that the *_base amounts are converted into.
    base_currency = Column(String(10), nullable=True)
    # exchange_rate_to_base - NUMERIC(18,8), optional.
    # Rate used to convert the document currency into the base currency.
    exchange_rate_to_base = Column(Numeric(18, 8), nullable=True)
    # total_amount_base - NUMERIC(14,2), optional.
    # Total in base currency.
    total_amount_base = Column(Numeric(14, 2), nullable=True)
    # advance_amount_base - NUMERIC(14,2), optional.
    # Advance in base currency.
    advance_amount_base = Column(Numeric(14, 2), nullable=True)
    # balance_amount_base - NUMERIC(14,2), optional.
    # Balance in base currency.
    balance_amount_base = Column(Numeric(14, 2), nullable=True)

    # Company / Consignee legacy fields
    # sheet_type - VARCHAR(50), optional, default NOBLE.
    # Legacy company sheet: NOBLE, SAHAJANAND or SAHAJ.
    sheet_type = Column(String(50), default="NOBLE")  # NOBLE, SAHAJANAND, SAHAJ
    # consignee - VARCHAR(255), optional.
    # Consignee name (legacy text).
    consignee = Column(String(255), nullable=True)
    # year - INTEGER, optional.
    # Year of the order.
    year = Column(Integer, nullable=True)
    # urgent_action - BOOLEAN, optional, default False.
    # True = flagged as urgent.
    urgent_action = Column(Boolean, default=False)

    # Purchasing Milestone Dates
    # order_mail_date - DATE, optional.
    # Date the request was made.
    order_mail_date = Column(Date, nullable=True)      # Request Date
    # quote_sent_date - DATE, optional.
    # Date quotes were asked for.
    quote_sent_date = Column(Date, nullable=True)      # Asked for Quote
    # quote_received_date - DATE, optional.
    # Date quote was received.
    quote_received_date = Column(Date, nullable=True)  # Received Quote
    # pi_confirmed_date - DATE, optional.
    # Date the quote/proforma was confirmed.
    pi_confirmed_date = Column(Date, nullable=True)    # Confirm-Quote / PI
    # payment_date - DATE, optional.
    # Advance payment date.
    payment_date = Column(Date, nullable=True)         # Advance Payment Date
    # balance_payment_date - DATE, optional.
    # Balance payment date.
    balance_payment_date = Column(Date, nullable=True) # Balance Payment Date
    # eta_date - DATE, optional.
    # Expected arrival date.
    eta_date = Column(Date, nullable=True)
    # freight_type - VARCHAR(50), optional, default Sea Freight.
    # Sea Freight, Air Freight...
    freight_type = Column(String(50), default="Sea Freight")
    # remark - TEXT, optional.
    # General remark.
    remark = Column(Text, nullable=True)
    # hold_reason - VARCHAR(500), optional.
    # Why the order is on hold.
    hold_reason = Column(String(500), nullable=True)
    # hold_type - VARCHAR(50), optional.
    # Kind of hold.
    hold_type = Column(String(50), nullable=True)

    # Relationships
    supplier_rel = relationship("Supplier", foreign_keys=[supplier_id], lazy="joined")
    order_status_rel = relationship("OrderStatus", foreign_keys=[status_id], lazy="joined")
    store_request = relationship("StoreRequest", back_populates="purchase_orders")
    
    items = relationship("POItem", back_populates="purchase_order", cascade="all, delete-orphan")
    documents = relationship("OrderDocument", back_populates="purchase_order", cascade="all, delete-orphan")
    payments = relationship("OrderPayment", back_populates="purchase_order", cascade="all, delete-orphan")
    proformas = relationship("ProformaInvoice", back_populates="purchase_order", foreign_keys="ProformaInvoice.po_id", cascade="all, delete-orphan")
    shipments = relationship("OrderShipment", back_populates="purchase_order", cascade="all, delete-orphan")
    packing_lists = relationship("OrderPackingList", back_populates="purchase_order", cascade="all, delete-orphan")
    receipts = relationship("GoodsReceipt", back_populates="purchase_order")
    defects = relationship("DefectReport", back_populates="purchase_order")
    status_history = relationship("OrderStatusHistory", back_populates="purchase_order", cascade="all, delete-orphan")
    
    quotes = relationship("VendorQuote", back_populates="purchase_order", foreign_keys="VendorQuote.po_id", cascade="all, delete-orphan")
    selected_quote = relationship("VendorQuote", foreign_keys=[selected_quote_id], lazy="joined", post_update=True)
    stage_transitions = relationship("POStageTransition", back_populates="purchase_order", cascade="all, delete-orphan")
    version_snapshots = relationship("POVersionSnapshot", back_populates="purchase_order", cascade="all, delete-orphan", order_by="POVersionSnapshot.id.desc()")
    
    parent_rfq = relationship("PurchaseOrder", remote_side=[id], foreign_keys=[parent_rfq_id], backref="child_pos")

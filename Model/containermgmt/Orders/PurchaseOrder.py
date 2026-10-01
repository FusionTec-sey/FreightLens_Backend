from sqlalchemy import Column, Integer, String, Boolean, Date, Text, ForeignKey, JSON, Numeric
from sqlalchemy.orm import relationship
from ...db import Base
from ...mixins import AuditMixin, OrgMixin

class PurchaseOrder(OrgMixin, AuditMixin, Base):
    __tablename__ = "purchase_orders"
    __table_args__ = {'schema': 'containermgmt'}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    po_number = Column(String(100), nullable=False, unique=True, index=True)
    po_nce = Column(String(100), nullable=True)  # PO Reference (Internal Accounts Reference / NPO)
    
    # Document classification & lineage: RFQ (pre-award) vs PO (binding order)
    doc_type = Column(String(20), nullable=False, default="PO", index=True)  # "RFQ" or "PO"
    parent_rfq_id = Column(Integer, ForeignKey("containermgmt.purchase_orders.id", ondelete="SET NULL"), nullable=True, index=True)
    origin_rfq_number = Column(String(100), nullable=True)  # e.g. "RFQ-2026-0042"
    split_index = Column(String(10), nullable=True)  # "A", "B", "C", etc.

    # Store request link
    request_id = Column(Integer, ForeignKey("containermgmt.store_requests.id"), nullable=True, index=True)
    
    supplier_id = Column(Integer, ForeignKey("containermgmt.supplier.supplier_id"), nullable=True)
    company = Column(String(255), nullable=True)  # Supplier company name fallback
    goods_description = Column(Text, nullable=True)
    material_ids = Column(JSON, nullable=True)  # List of selected material IDs

    # Main Lifecycle Status (references order_status table)
    status_id = Column(Integer, ForeignKey("containermgmt.order_status.id"), nullable=True)
    status = Column(String(50), default="DRAFT", index=True)  # DRAFT, SUBMITTED, SOURCING, ORDERED, etc.
    status_label = Column(String(100), default="Draft")

    # ── Procurement Lifecycle Stage (7-stage pipeline) ───────────────────
    # DRAFT -> CONFIRMED -> RFQ_SENT -> QUOTE_RECEIVED -> QUOTE_APPROVED -> PO_ISSUED -> PROFORMA
    lifecycle_stage = Column(String(30), nullable=False, default="DRAFT", index=True)
    stage_version = Column(Integer, nullable=False, default=1) # Version within current stage (e.g., Draft v1, Draft v2, Confirmed v1)
    lifecycle_version = Column(Integer, nullable=False, default=1) # Sequential concurrency counter
    lifecycle_locked = Column(Boolean, nullable=False, default=False)
    selected_quote_id = Column(Integer, ForeignKey("containermgmt.vendor_quotes.id", ondelete="SET NULL"), nullable=True)

    # Distinct Tracking Dimensions (preventing single-remark overload)
    payment_status = Column(String(50), default="NONE")       # NONE, ADVANCE_PAID, PART_PAID, FULLY_PAID
    production_status = Column(String(50), default="NOT_STARTED") # NOT_STARTED, IN_PRODUCTION, READY
    shipment_status = Column(String(50), default="NOT_SHIPPED")   # NOT_SHIPPED, PARTIALLY_SHIPPED, SHIPPED, ARRIVED
    receipt_status = Column(String(50), default="PENDING")        # PENDING, PARTIALLY_RECEIVED, RECEIVED

    # Financial details (confidential - visible to Accounts/Management)
    total_amount = Column(Numeric(14, 2), nullable=True)
    advance_amount = Column(Numeric(14, 2), nullable=True)
    balance_amount = Column(Numeric(14, 2), nullable=True)
    currency = Column(String(10), default="USD")
    base_currency = Column(String(10), nullable=True)
    exchange_rate_to_base = Column(Numeric(18, 8), nullable=True)
    total_amount_base = Column(Numeric(14, 2), nullable=True)
    advance_amount_base = Column(Numeric(14, 2), nullable=True)
    balance_amount_base = Column(Numeric(14, 2), nullable=True)

    # Company / Consignee legacy fields
    sheet_type = Column(String(50), default="NOBLE")  # NOBLE, SAHAJANAND, SAHAJ
    consignee = Column(String(255), nullable=True)
    year = Column(Integer, nullable=True)
    urgent_action = Column(Boolean, default=False)

    # Purchasing Milestone Dates
    order_mail_date = Column(Date, nullable=True)      # Request Date
    quote_sent_date = Column(Date, nullable=True)      # Asked for Quote
    quote_received_date = Column(Date, nullable=True)  # Received Quote
    pi_confirmed_date = Column(Date, nullable=True)    # Confirm-Quote / PI
    payment_date = Column(Date, nullable=True)         # Advance Payment Date
    balance_payment_date = Column(Date, nullable=True) # Balance Payment Date
    eta_date = Column(Date, nullable=True)
    freight_type = Column(String(50), default="Sea Freight")
    remark = Column(Text, nullable=True)
    hold_reason = Column(String(500), nullable=True)
    hold_type = Column(String(50), nullable=True)

    # Relationships
    supplier_rel = relationship("Supplier", foreign_keys=[supplier_id], lazy="joined")
    order_status_rel = relationship("OrderStatus", foreign_keys=[status_id], lazy="joined")
    store_request = relationship("StoreRequest", back_populates="purchase_orders")
    
    items = relationship("POItem", back_populates="purchase_order", cascade="all, delete-orphan")
    documents = relationship("OrderDocument", back_populates="purchase_order", cascade="all, delete-orphan")
    payments = relationship("OrderPayment", back_populates="purchase_order", cascade="all, delete-orphan")
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

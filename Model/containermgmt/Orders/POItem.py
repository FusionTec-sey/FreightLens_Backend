from sqlalchemy import Column, Integer, String, Text, ForeignKey, Numeric
from sqlalchemy.orm import relationship
from ...db import Base
from ...mixins import AuditMixin, OrgMixin

# TABLE: A line on an RFQ or purchase order.
class POItem(OrgMixin, AuditMixin, Base):
    __tablename__ = "po_items"
    __table_args__ = {'schema': 'containermgmt'}

    # id - INTEGER, primary key.
    # Unique row number.
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    # po_id - INTEGER, foreign key -> containermgmt.purchase_orders.id, required.
    # Purchase order (or RFQ) this row belongs to.
    po_id = Column(Integer, ForeignKey("containermgmt.purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    # request_item_id - INTEGER, foreign key -> containermgmt.store_request_items.id, optional.
    # Store request line this came from.
    request_item_id = Column(Integer, ForeignKey("containermgmt.store_request_items.id"), nullable=True, index=True)
    
    # item_code - VARCHAR(100), optional.
    # Item/article code for this line.
    item_code = Column(String(100), nullable=True)
    # description - TEXT, required.
    # Free-text description.
    description = Column(Text, nullable=False)
    # What the RFQ asked for, kept beside what was agreed. They differ whenever a
    # vendor's minimum, carton multiple or substitute is accepted at award, and
    # the difference is the thing a buyer needs to see on the order.
    # quantity_requested - NUMERIC(12,2), optional.
    # Quantity asked for in the RFQ.
    quantity_requested = Column(Numeric(12, 2), nullable=True)
    # Conversion of an RFQ to a PO: why the quantity ordered differs from the
    # request (MOQ, PACK_MULTIPLE, OTHER).
    # qty_adjust_reason - VARCHAR(20), optional.
    # Why ordered quantity differs from requested: MOQ, PACK_MULTIPLE or OTHER.
    qty_adjust_reason = Column(String(20), nullable=True)
    # qty_adjust_note - VARCHAR(500), optional.
    # Explanation of the adjustment.
    qty_adjust_note = Column(String(500), nullable=True)
    # quantity_ordered - NUMERIC(12,2), required, default 1.0.
    # Quantity agreed/ordered.
    quantity_ordered = Column(Numeric(12, 2), nullable=False, default=1.0)
    # quantity_packed - NUMERIC(12,2), required, default 0.0.
    # Quantity packed so far.
    quantity_packed = Column(Numeric(12, 2), nullable=False, default=0.0)
    # quantity_received - NUMERIC(12,2), required, default 0.0.
    # Quantity received so far.
    quantity_received = Column(Numeric(12, 2), nullable=False, default=0.0)
    # unit - VARCHAR(50), optional, default PCS.
    # Unit of measure, e.g. PCS, KG.
    unit = Column(String(50), default="PCS")
    
    # unit_price - NUMERIC(14,2), optional.
    # Current price per unit.
    unit_price = Column(Numeric(14, 2), nullable=True)
    # total_price - NUMERIC(14,2), optional.
    # Line total (quantity x price).
    total_price = Column(Numeric(14, 2), nullable=True)
    # currency - VARCHAR(10), optional, default USD.
    # Currency code of the amounts on this row (e.g. USD, SCR).
    currency = Column(String(10), default="USD")
    # base_currency - VARCHAR(10), optional.
    # Company reporting currency that the *_base amounts are converted into.
    base_currency = Column(String(10), nullable=True)
    # exchange_rate_to_base - NUMERIC(18,8), optional.
    # Rate used to convert the document currency into the base currency.
    exchange_rate_to_base = Column(Numeric(18, 8), nullable=True)
    # unit_price_base - NUMERIC(14,2), optional.
    # Unit price in base currency.
    unit_price_base = Column(Numeric(14, 2), nullable=True)
    # total_price_base - NUMERIC(14,2), optional.
    # Line total in base currency.
    total_price_base = Column(Numeric(14, 2), nullable=True)
    
    # ── Multi-Stage Prices ───────────────────────────────────────────────
    # draft_unit_price - NUMERIC(14,2), optional.
    # Estimated price during draft.
    draft_unit_price = Column(Numeric(14, 2), nullable=True)       # Estimated price during Draft
    # approved_unit_price - NUMERIC(14,2), optional.
    # Internally signed-off price.
    approved_unit_price = Column(Numeric(14, 2), nullable=True)    # Internal signed-off price
    # po_unit_price - NUMERIC(14,2), optional.
    # Price when the official PO was issued.
    po_unit_price = Column(Numeric(14, 2), nullable=True)          # Price when official PO was issued
    # proforma_unit_price - NUMERIC(14,2), optional.
    # Final price on the vendor proforma.
    proforma_unit_price = Column(Numeric(14, 2), nullable=True)    # Final price on Proforma invoice

    # ── Lifecycle Item Status ────────────────────────────────────────────
    # ACTIVE, USER_REMOVED, VENDOR_REJECTED, SUBSTITUTED
    # item_status - VARCHAR(30), required, default ACTIVE.
    # ACTIVE, USER_REMOVED, VENDOR_REJECTED or SUBSTITUTED.
    item_status = Column(String(30), nullable=False, default="ACTIVE")
    # removed_at_stage - VARCHAR(30), optional.
    # Lifecycle stage at which the line was removed.
    removed_at_stage = Column(String(30), nullable=True)
    # substituted_by_id - INTEGER, foreign key -> containermgmt.po_items.id, optional.
    # Line that replaced this one.
    substituted_by_id = Column(Integer, ForeignKey("containermgmt.po_items.id", ondelete="SET NULL"), nullable=True)
    # original_item_id - INTEGER, foreign key -> containermgmt.po_items.id, optional.
    # Line this one replaced.
    original_item_id = Column(Integer, ForeignKey("containermgmt.po_items.id", ondelete="SET NULL"), nullable=True)

    # notes - TEXT, optional.
    # Free-text remarks.
    notes = Column(Text, nullable=True)
    # product_id - INTEGER, foreign key -> containermgmt.products.id, optional.
    # Product (catalogue item) this row refers to.
    product_id = Column(Integer, ForeignKey("containermgmt.products.id", ondelete="SET NULL"), nullable=True, index=True)

    # ── RFQ Lineage & Split-Award Fields ─────────────────────────────────
    # source_rfq_item_id - INTEGER, foreign key -> containermgmt.po_items.id, optional.
    # RFQ line this PO line was created from.
    source_rfq_item_id = Column(Integer, ForeignKey("containermgmt.po_items.id", ondelete="SET NULL"), nullable=True)
    # awarded_vendor_id - INTEGER, foreign key -> containermgmt.supplier.supplier_id, optional.
    # Vendor that won this line.
    awarded_vendor_id = Column(Integer, ForeignKey("containermgmt.supplier.supplier_id"), nullable=True)
    # awarded_quote_id - INTEGER, foreign key -> containermgmt.vendor_quotes.id, optional.
    # Quote that won this line.
    awarded_quote_id = Column(Integer, ForeignKey("containermgmt.vendor_quotes.id"), nullable=True)

    # Relationships
    purchase_order = relationship("PurchaseOrder", back_populates="items")
    request_item = relationship("StoreRequestItem", back_populates="po_items")
    packing_items = relationship("PackingListItem", back_populates="po_item")
    receipt_items = relationship("ReceiptItem", back_populates="po_item")
    product = relationship("Product", back_populates="po_items")
    history = relationship("POItemHistory", back_populates="po_item", cascade="all, delete-orphan", order_by="POItemHistory.created_at.desc()")
    source_rfq_item = relationship("POItem", remote_side=[id], foreign_keys=[source_rfq_item_id])

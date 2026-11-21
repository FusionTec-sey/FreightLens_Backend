from sqlalchemy import Column, Integer, String, Text, DateTime, Date, ForeignKey, Numeric, Boolean
from sqlalchemy.orm import relationship
from ...db import Base
from ...mixins import AuditMixin, OrgMixin

# TABLE: Goods Receipt Note (GRN): record of goods actually received at the warehouse.
class GoodsReceipt(OrgMixin, AuditMixin, Base):
    __tablename__ = "goods_receipts"
    __table_args__ = {'schema': 'containermgmt'}

    # id - INTEGER, primary key.
    # Unique row number.
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    # receipt_number - VARCHAR(100), required, unique.
    # Document number, e.g. GRN-2026-0001.
    receipt_number = Column(String(100), unique=True, nullable=False, index=True)  # e.g. GRN-2026-0001
    
    # po_id - INTEGER, foreign key -> containermgmt.purchase_orders.id, required.
    # Purchase order (or RFQ) this row belongs to.
    po_id = Column(Integer, ForeignKey("containermgmt.purchase_orders.id"), nullable=False, index=True)
    # packing_list_id - INTEGER, foreign key -> containermgmt.order_packing_lists.id, optional.
    # Packing list this receipt was checked against.
    packing_list_id = Column(Integer, ForeignKey("containermgmt.order_packing_lists.id"), nullable=True, index=True)
    # container_id - INTEGER, foreign key -> containermgmt.container_details.Container_ID, optional.
    # Container this row refers to.
    container_id = Column(Integer, ForeignKey("containermgmt.container_details.Container_ID"), nullable=True, index=True)
    
    # warehouse_location - VARCHAR(150), optional.
    # Where the goods were stored.
    warehouse_location = Column(String(150), nullable=True)
    # received_date - DATE, required.
    # Date goods were received.
    received_date = Column(Date, nullable=False)
    # received_by - INTEGER, foreign key -> usercredentials.users.id, optional.
    # User who received them.
    received_by = Column(Integer, ForeignKey("usercredentials.users.id"), nullable=True)
    
    # Status: DRAFT, SUBMITTED, DISCREPANCY, VERIFIED
    # status - VARCHAR(50), optional, default DRAFT.
    # DRAFT, SUBMITTED, DISCREPANCY or VERIFIED.
    status = Column(String(50), default="DRAFT", index=True)
    # has_discrepancies - BOOLEAN, optional, default False.
    # True if any line differs from what was expected.
    has_discrepancies = Column(Boolean, default=False)
    
    # notes - TEXT, optional.
    # Free-text remarks.
    notes = Column(Text, nullable=True)
    # submitted_at - TIMESTAMP WITH TIME ZONE, optional.
    # When the receipt was submitted.
    submitted_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    purchase_order = relationship("PurchaseOrder", back_populates="receipts")
    packing_list = relationship("OrderPackingList", back_populates="receipts")
    container = relationship("ContainerDetails", foreign_keys=[container_id], lazy="joined")
    receiver = relationship("User", foreign_keys=[received_by], viewonly=True)
    items = relationship("ReceiptItem", back_populates="receipt", cascade="all, delete-orphan")
    defects = relationship("DefectReport", back_populates="receipt")


# TABLE: Expected vs actual quantities per line of a goods receipt.
class ReceiptItem(AuditMixin, Base):
    __tablename__ = "goods_receipt_items"
    __table_args__ = {'schema': 'containermgmt'}

    # id - INTEGER, primary key.
    # Unique row number.
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    # receipt_id - INTEGER, foreign key -> containermgmt.goods_receipts.id, required.
    # Receipt this line belongs to.
    receipt_id = Column(Integer, ForeignKey("containermgmt.goods_receipts.id", ondelete="CASCADE"), nullable=False, index=True)
    # po_item_id - INTEGER, foreign key -> containermgmt.po_items.id, optional.
    # PO line being received.
    po_item_id = Column(Integer, ForeignKey("containermgmt.po_items.id"), nullable=True, index=True)
    # packing_item_id - INTEGER, foreign key -> containermgmt.order_packing_list_items.id, optional.
    # Packing-list line being checked.
    packing_item_id = Column(Integer, ForeignKey("containermgmt.order_packing_list_items.id"), nullable=True, index=True)
    
    # description - TEXT, required.
    # Free-text description.
    description = Column(Text, nullable=False)
    # expected_quantity - NUMERIC(12,2), required, default 0.0.
    # Quantity that should have arrived.
    expected_quantity = Column(Numeric(12, 2), nullable=False, default=0.0)
    # received_quantity - NUMERIC(12,2), required, default 0.0.
    # Quantity that actually arrived.
    received_quantity = Column(Numeric(12, 2), nullable=False, default=0.0)
    
    # missing_quantity - NUMERIC(12,2), optional, default 0.0.
    # Quantity short.
    missing_quantity = Column(Numeric(12, 2), default=0.0)
    # excess_quantity - NUMERIC(12,2), optional, default 0.0.
    # Quantity over.
    excess_quantity = Column(Numeric(12, 2), default=0.0)
    # damaged_quantity - NUMERIC(12,2), optional, default 0.0.
    # Quantity damaged.
    damaged_quantity = Column(Numeric(12, 2), default=0.0)
    # incorrect_quantity - NUMERIC(12,2), optional, default 0.0.
    # Quantity of the wrong item.
    incorrect_quantity = Column(Numeric(12, 2), default=0.0)
    
    # unit - VARCHAR(50), optional, default PCS.
    # Unit of measure, e.g. PCS, KG.
    unit = Column(String(50), default="PCS")
    # condition_ok - BOOLEAN, optional, default True.
    # False if the goods were not in good condition.
    condition_ok = Column(Boolean, default=True)
    # notes - TEXT, optional.
    # Free-text remarks.
    notes = Column(Text, nullable=True)
    # photo_url - VARCHAR(500), optional.
    # Photo of the goods.
    photo_url = Column(String(500), nullable=True)

    # Relationships
    receipt = relationship("GoodsReceipt", back_populates="items")
    po_item = relationship("POItem", back_populates="receipt_items")
    packing_item = relationship("PackingListItem", back_populates="receipt_items")

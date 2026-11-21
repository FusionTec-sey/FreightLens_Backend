from sqlalchemy import Column, Integer, String, Text, Date, ForeignKey, Numeric
from sqlalchemy.orm import relationship
from ...db import Base
from ...mixins import AuditMixin, OrgMixin

# TABLE: A claim for shortage, damage, wrong or poor-quality goods or container damage.
class DefectReport(OrgMixin, AuditMixin, Base):
    __tablename__ = "defect_reports"
    __table_args__ = {'schema': 'containermgmt'}

    # id - INTEGER, primary key.
    # Unique row number.
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    # defect_number - VARCHAR(100), required, unique.
    # Document number, e.g. DEF-2026-0001.
    defect_number = Column(String(100), unique=True, nullable=False, index=True)  # e.g. DEF-2026-0001
    
    # Category / Type:
    # GOODS_DEFECT: Shortage, Excess, Wrong Item, Quality Issue, Specification Mismatch
    # CONTAINER_DAMAGE: Unloading Damage, Handling Damage, In-Transit Damage, Concealed Damage
    # report_type - VARCHAR(50), required, default GOODS_DEFECT.
    # GOODS_DEFECT or CONTAINER_DAMAGE.
    report_type = Column(String(50), nullable=False, default="GOODS_DEFECT", index=True)
    # category - VARCHAR(100), required.
    # Shortage, Damaged, Wrong Item, Quality, Unloading...
    category = Column(String(100), nullable=False)  # Shortage, Damaged, Wrong Item, Quality, Unloading, etc.
    
    # po_id - INTEGER, foreign key -> containermgmt.purchase_orders.id, optional.
    # Purchase order (or RFQ) this row belongs to.
    po_id = Column(Integer, ForeignKey("containermgmt.purchase_orders.id"), nullable=True, index=True)
    # receipt_id - INTEGER, foreign key -> containermgmt.goods_receipts.id, optional.
    # Goods receipt where the problem was found.
    receipt_id = Column(Integer, ForeignKey("containermgmt.goods_receipts.id"), nullable=True, index=True)
    # container_id - INTEGER, foreign key -> containermgmt.container_details.Container_ID, optional.
    # Container this row refers to.
    container_id = Column(Integer, ForeignKey("containermgmt.container_details.Container_ID"), nullable=True, index=True)
    # bill_of_lading_no - VARCHAR(100), foreign key -> containermgmt.bill_of_landing.BillOfLanding,
    # optional.
    # Bill of lading involved.
    bill_of_lading_no = Column(String(100), ForeignKey("containermgmt.bill_of_landing.BillOfLanding"), nullable=True, index=True)
    
    # Dates: Unloading milestone vs Discovery date
    # unloading_date - DATE, optional.
    # Date the container was unloaded.
    unloading_date = Column(Date, nullable=True)
    # discovery_date - DATE, required.
    # Date the problem was noticed.
    discovery_date = Column(Date, nullable=False)
    
    # title - VARCHAR(255), required.
    # Short headline.
    title = Column(String(255), nullable=False)
    # description - TEXT, optional.
    # Free-text description.
    description = Column(Text, nullable=True)
    
    # Status: OPEN, UNDER_REVIEW, RESOLUTION_PENDING, RESOLVED, CLOSED
    # status - VARCHAR(50), optional, default OPEN.
    # OPEN, UNDER_REVIEW, RESOLUTION_PENDING, RESOLVED or CLOSED.
    status = Column(String(50), default="OPEN", index=True)
    
    # Resolution Type: REPLACEMENT, CREDIT_NOTE, REFUND, ACCEPTED_AS_IS, CLOSED_WITHOUT_ACTION
    # resolution_type - VARCHAR(50), optional.
    # REPLACEMENT, CREDIT_NOTE, REFUND, ACCEPTED_AS_IS or CLOSED_WITHOUT_ACTION.
    resolution_type = Column(String(50), nullable=True)
    # resolution_notes - TEXT, optional.
    # How it was settled.
    resolution_notes = Column(Text, nullable=True)
    # resolved_at - DATE, optional.
    # Date resolved.
    resolved_at = Column(Date, nullable=True)
    # resolved_by - INTEGER, foreign key -> usercredentials.users.id, optional.
    # User who resolved it.
    resolved_by = Column(Integer, ForeignKey("usercredentials.users.id"), nullable=True)

    # Relationships
    purchase_order = relationship("PurchaseOrder", back_populates="defects")
    receipt = relationship("GoodsReceipt", back_populates="defects")
    container = relationship("ContainerDetails", foreign_keys=[container_id], lazy="joined")
    bill_of_lading = relationship("BillOfLanding", foreign_keys=[bill_of_lading_no], lazy="joined")
    items = relationship("DefectItem", back_populates="defect_report", cascade="all, delete-orphan")
    images = relationship("DefectImage", back_populates="defect_report", cascade="all, delete-orphan")


# TABLE: Items affected by a defect report.
class DefectItem(AuditMixin, Base):
    __tablename__ = "defect_items"
    __table_args__ = {'schema': 'containermgmt'}

    # id - INTEGER, primary key.
    # Unique row number.
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    # defect_id - INTEGER, foreign key -> containermgmt.defect_reports.id, required.
    # Defect report this item belongs to.
    defect_id = Column(Integer, ForeignKey("containermgmt.defect_reports.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # item_description - TEXT, required.
    # What the affected item is.
    item_description = Column(Text, nullable=False)
    # quantity_affected - NUMERIC(12,2), required, default 1.0.
    # How many units are affected.
    quantity_affected = Column(Numeric(12, 2), nullable=False, default=1.0)
    # unit - VARCHAR(50), optional, default PCS.
    # Unit of measure, e.g. PCS, KG.
    unit = Column(String(50), default="PCS")
    # notes - TEXT, optional.
    # Free-text remarks.
    notes = Column(Text, nullable=True)

    # Relationship
    defect_report = relationship("DefectReport", back_populates="items")


# TABLE: Evidence photos for a defect report.
class DefectImage(AuditMixin, Base):
    __tablename__ = "defect_images"
    __table_args__ = {'schema': 'containermgmt'}

    # id - INTEGER, primary key.
    # Unique row number.
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    # defect_id - INTEGER, foreign key -> containermgmt.defect_reports.id, required.
    # Defect report this photo belongs to.
    defect_id = Column(Integer, ForeignKey("containermgmt.defect_reports.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # file_path - VARCHAR(500), required.
    # Storage key/URL of the photo.
    file_path = Column(String(500), nullable=False)  # RustFS key / URL
    # caption - VARCHAR(255), optional.
    # Caption for the photo.
    caption = Column(String(255), nullable=True)

    # Relationship
    defect_report = relationship("DefectReport", back_populates="images")

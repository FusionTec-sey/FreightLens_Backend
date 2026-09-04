from sqlalchemy import Column, Integer, String, Text, Date, ForeignKey, Numeric
from sqlalchemy.orm import relationship
from ...db import Base
from ...mixins import AuditMixin, OrgMixin

class DefectReport(OrgMixin, AuditMixin, Base):
    __tablename__ = "defect_reports"
    __table_args__ = {'schema': 'containermgmt'}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    defect_number = Column(String(100), unique=True, nullable=False, index=True)  # e.g. DEF-2026-0001
    
    # Category / Type:
    # GOODS_DEFECT: Shortage, Excess, Wrong Item, Quality Issue, Specification Mismatch
    # CONTAINER_DAMAGE: Unloading Damage, Handling Damage, In-Transit Damage, Concealed Damage
    report_type = Column(String(50), nullable=False, default="GOODS_DEFECT", index=True)
    category = Column(String(100), nullable=False)  # Shortage, Damaged, Wrong Item, Quality, Unloading, etc.
    
    po_id = Column(Integer, ForeignKey("containermgmt.purchase_orders.id"), nullable=True, index=True)
    receipt_id = Column(Integer, ForeignKey("containermgmt.goods_receipts.id"), nullable=True, index=True)
    container_id = Column(Integer, ForeignKey("containermgmt.container_details.Container_ID"), nullable=True, index=True)
    bill_of_lading_no = Column(String(100), ForeignKey("containermgmt.bill_of_landing.BillOfLanding"), nullable=True, index=True)
    
    # Dates: Unloading milestone vs Discovery date
    unloading_date = Column(Date, nullable=True)
    discovery_date = Column(Date, nullable=False)
    
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    
    # Status: OPEN, UNDER_REVIEW, RESOLUTION_PENDING, RESOLVED, CLOSED
    status = Column(String(50), default="OPEN", index=True)
    
    # Resolution Type: REPLACEMENT, CREDIT_NOTE, REFUND, ACCEPTED_AS_IS, CLOSED_WITHOUT_ACTION
    resolution_type = Column(String(50), nullable=True)
    resolution_notes = Column(Text, nullable=True)
    resolved_at = Column(Date, nullable=True)
    resolved_by = Column(Integer, ForeignKey("usercredentials.users.id"), nullable=True)

    # Relationships
    purchase_order = relationship("PurchaseOrder", back_populates="defects")
    receipt = relationship("GoodsReceipt", back_populates="defects")
    container = relationship("ContainerDetails", foreign_keys=[container_id], lazy="joined")
    bill_of_lading = relationship("BillOfLanding", foreign_keys=[bill_of_lading_no], lazy="joined")
    items = relationship("DefectItem", back_populates="defect_report", cascade="all, delete-orphan")
    images = relationship("DefectImage", back_populates="defect_report", cascade="all, delete-orphan")


class DefectItem(AuditMixin, Base):
    __tablename__ = "defect_items"
    __table_args__ = {'schema': 'containermgmt'}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    defect_id = Column(Integer, ForeignKey("containermgmt.defect_reports.id", ondelete="CASCADE"), nullable=False, index=True)
    
    item_description = Column(Text, nullable=False)
    quantity_affected = Column(Numeric(12, 2), nullable=False, default=1.0)
    unit = Column(String(50), default="PCS")
    notes = Column(Text, nullable=True)

    # Relationship
    defect_report = relationship("DefectReport", back_populates="items")


class DefectImage(AuditMixin, Base):
    __tablename__ = "defect_images"
    __table_args__ = {'schema': 'containermgmt'}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    defect_id = Column(Integer, ForeignKey("containermgmt.defect_reports.id", ondelete="CASCADE"), nullable=False, index=True)
    
    file_path = Column(String(500), nullable=False)  # RustFS key / URL
    caption = Column(String(255), nullable=True)

    # Relationship
    defect_report = relationship("DefectReport", back_populates="images")

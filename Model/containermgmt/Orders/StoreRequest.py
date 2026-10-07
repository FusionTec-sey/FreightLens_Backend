from sqlalchemy import Column, Integer, String, Text, DateTime, Date, ForeignKey, Numeric, Boolean
from sqlalchemy.orm import relationship
from ...db import Base
from ...mixins import AuditMixin, OrgMixin

class StoreRequest(OrgMixin, AuditMixin, Base):
    __tablename__ = "store_requests"
    __table_args__ = {'schema': 'containermgmt'}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    request_number = Column(String(100), unique=True, nullable=False, index=True)  # e.g. REQ-2026-0001
    title = Column(String(255), nullable=True)
    department = Column(String(100), nullable=True)
    store_location = Column(String(150), nullable=True)
    
    # Lifecycle: DRAFT, SUBMITTED, SOURCING, ORDERED, PARTIALLY_FULFILLED, COMPLETED, CANCELLED, WITHDRAWN
    status = Column(String(50), default="DRAFT", index=True)
    status_label = Column(String(100), default="Draft")
    
    required_date = Column(Date, nullable=True)
    notes = Column(Text, nullable=True)
    hold_reason = Column(String(500), nullable=True)
    hold_type = Column(String(50), nullable=True)
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    submitted_by = Column(Integer, ForeignKey("usercredentials.users.id"), nullable=True)

    # Relationships
    items = relationship("StoreRequestItem", back_populates="request", cascade="all, delete-orphan")
    purchase_orders = relationship("PurchaseOrder", back_populates="store_request")
    submitter = relationship("User", foreign_keys=[submitted_by], viewonly=True)


class StoreRequestItem(AuditMixin, Base):
    __tablename__ = "store_request_items"
    __table_args__ = {'schema': 'containermgmt'}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    request_id = Column(Integer, ForeignKey("containermgmt.store_requests.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("containermgmt.products.id", ondelete="SET NULL"), nullable=True, index=True)
    
    item_code = Column(String(100), nullable=True)
    description = Column(Text, nullable=False)
    quantity_requested = Column(Numeric(12, 2), nullable=False, default=1.0)
    quantity_ordered = Column(Numeric(12, 2), nullable=False, default=0.0)
    quantity_received = Column(Numeric(12, 2), nullable=False, default=0.0)
    unit = Column(String(50), default="PCS")
    
    required_date = Column(Date, nullable=True)
    notes = Column(Text, nullable=True)
    image_url = Column(String(500), nullable=True)
    template_item_id = Column(Integer, nullable=True)

    # Relationships
    request = relationship("StoreRequest", back_populates="items")
    product = relationship("Product", foreign_keys=[product_id])
    po_items = relationship("POItem", back_populates="request_item")

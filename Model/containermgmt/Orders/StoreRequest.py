from sqlalchemy import Column, Integer, String, Text, DateTime, Date, ForeignKey, Numeric, Boolean
from sqlalchemy.orm import relationship
from ...db import Base
from ...mixins import AuditMixin, OrgMixin

# TABLE: Internal 'we need these items' request from a department.
class StoreRequest(OrgMixin, AuditMixin, Base):
    __tablename__ = "store_requests"
    __table_args__ = {'schema': 'containermgmt'}

    # id - INTEGER, primary key.
    # Unique row number.
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    # request_number - VARCHAR(100), required, unique.
    # Document number, e.g. REQ-2026-0001.
    request_number = Column(String(100), unique=True, nullable=False, index=True)  # e.g. REQ-2026-0001
    # title - VARCHAR(255), optional.
    # Short title.
    title = Column(String(255), nullable=True)
    # department - VARCHAR(100), optional.
    # Requesting department.
    department = Column(String(100), nullable=True)
    # store_location - VARCHAR(150), optional.
    # Store the goods are for.
    store_location = Column(String(150), nullable=True)
    
    # Lifecycle: DRAFT, SUBMITTED, SOURCING, ORDERED, PARTIALLY_FULFILLED, COMPLETED, CANCELLED, WITHDRAWN
    # status - VARCHAR(50), optional, default DRAFT.
    # DRAFT, SUBMITTED, SOURCING, ORDERED, PARTIALLY_FULFILLED, COMPLETED, CANCELLED or WITHDRAWN.
    status = Column(String(50), default="DRAFT", index=True)
    # status_label - VARCHAR(100), optional, default Draft.
    # Readable status text.
    status_label = Column(String(100), default="Draft")
    
    # required_date - DATE, optional.
    # Date the goods are needed.
    required_date = Column(Date, nullable=True)
    # notes - TEXT, optional.
    # Free-text remarks.
    notes = Column(Text, nullable=True)
    # hold_reason - VARCHAR(500), optional.
    # Why the request is on hold.
    hold_reason = Column(String(500), nullable=True)
    # hold_type - VARCHAR(50), optional.
    # Kind of hold.
    hold_type = Column(String(50), nullable=True)
    # submitted_at - TIMESTAMP WITH TIME ZONE, optional.
    # When it was submitted.
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    # submitted_by - INTEGER, foreign key -> usercredentials.users.id, optional.
    # User who submitted it.
    submitted_by = Column(Integer, ForeignKey("usercredentials.users.id"), nullable=True)

    # Relationships
    items = relationship("StoreRequestItem", back_populates="request", cascade="all, delete-orphan")
    purchase_orders = relationship("PurchaseOrder", back_populates="store_request")
    submitter = relationship("User", foreign_keys=[submitted_by], viewonly=True)


# TABLE: Lines of a store request.
class StoreRequestItem(AuditMixin, Base):
    __tablename__ = "store_request_items"
    __table_args__ = {'schema': 'containermgmt'}

    # id - INTEGER, primary key.
    # Unique row number.
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    # request_id - INTEGER, foreign key -> containermgmt.store_requests.id, required.
    # Request this line belongs to.
    request_id = Column(Integer, ForeignKey("containermgmt.store_requests.id", ondelete="CASCADE"), nullable=False, index=True)
    # product_id - INTEGER, foreign key -> containermgmt.products.id, optional.
    # Product (catalogue item) this row refers to.
    product_id = Column(Integer, ForeignKey("containermgmt.products.id", ondelete="SET NULL"), nullable=True, index=True)
    
    # item_code - VARCHAR(100), optional.
    # Item/article code for this line.
    item_code = Column(String(100), nullable=True)
    # description - TEXT, required.
    # Free-text description.
    description = Column(Text, nullable=False)
    # quantity_requested - NUMERIC(12,2), required, default 1.0.
    # Quantity asked for.
    quantity_requested = Column(Numeric(12, 2), nullable=False, default=1.0)
    # quantity_ordered - NUMERIC(12,2), required, default 0.0.
    # Quantity ordered so far.
    quantity_ordered = Column(Numeric(12, 2), nullable=False, default=0.0)
    # quantity_received - NUMERIC(12,2), required, default 0.0.
    # Quantity received so far.
    quantity_received = Column(Numeric(12, 2), nullable=False, default=0.0)
    # unit - VARCHAR(50), optional, default PCS.
    # Unit of measure, e.g. PCS, KG.
    unit = Column(String(50), default="PCS")
    
    # required_date - DATE, optional.
    # Date this line is needed.
    required_date = Column(Date, nullable=True)
    # notes - TEXT, optional.
    # Free-text remarks.
    notes = Column(Text, nullable=True)
    # image_url - VARCHAR(500), optional.
    # Reference image.
    image_url = Column(String(500), nullable=True)
    # template_item_id - INTEGER, optional.
    # Template line it was created from.
    template_item_id = Column(Integer, nullable=True)

    # Relationships
    request = relationship("StoreRequest", back_populates="items")
    product = relationship("Product", foreign_keys=[product_id])
    po_items = relationship("POItem", back_populates="request_item")

from sqlalchemy import Column, Integer, String, Text, ForeignKey, JSON, Numeric, Boolean
from sqlalchemy.orm import relationship
from ...db import Base
from ...mixins import AuditMixin, OrgMixin

# TABLE: Saved repeat-order lists (e.g. a monthly hardware order).
class OrderTemplate(OrgMixin, AuditMixin, Base):
    __tablename__ = "order_templates"
    __table_args__ = {'schema': 'containermgmt'}

    # id - INTEGER, primary key.
    # Unique row number.
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    # name - VARCHAR(255), required.
    # Template name.
    name = Column(String(255), nullable=False)
    # description - TEXT, optional.
    # Free-text description.
    description = Column(Text, nullable=True)
    # tags - JSON, optional.
    # Free-form labels (JSON list) for searching and grouping.
    tags = Column(JSON, nullable=True)  # List of string tags, e.g. ["Hardware", "Monthly", "Urgent"]
    
    # supplier_id - INTEGER, foreign key -> containermgmt.supplier.supplier_id, optional.
    # Vendor this row refers to (supplier table).
    supplier_id = Column(Integer, ForeignKey("containermgmt.supplier.supplier_id", ondelete="SET NULL"), nullable=True)
    # company - VARCHAR(255), optional.
    # Vendor company name text if no vendor record is linked.
    company = Column(String(255), nullable=True)  # Fallback supplier company name
    # freight_type - VARCHAR(50), optional, default Sea Freight.
    # Sea Freight, Air Freight...
    freight_type = Column(String(50), default="Sea Freight")
    # notes - TEXT, optional.
    # Free-text remarks.
    notes = Column(Text, nullable=True)
    
    # Visibility: 'org' (visible to entire org) or 'private' (visible only to created_by)
    # visibility - VARCHAR(20), required, default org.
    # 'org' = whole company, 'private' = only the creator.
    visibility = Column(String(20), default="org", nullable=False)

    # Relationships
    supplier_rel = relationship("Supplier", foreign_keys=[supplier_id], lazy="joined")
    items = relationship(
        "OrderTemplateItem",
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="OrderTemplateItem.sort_order"
    )


# TABLE: Lines of an order template.
class OrderTemplateItem(AuditMixin, Base):
    __tablename__ = "order_template_items"
    __table_args__ = {'schema': 'containermgmt'}

    # id - INTEGER, primary key.
    # Unique row number.
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    # template_id - INTEGER, foreign key -> containermgmt.order_templates.id, required.
    # Template this line belongs to.
    template_id = Column(Integer, ForeignKey("containermgmt.order_templates.id", ondelete="CASCADE"), nullable=False, index=True)
    # product_id - INTEGER, foreign key -> containermgmt.products.id, optional.
    # Product (catalogue item) this row refers to.
    product_id = Column(Integer, ForeignKey("containermgmt.products.id", ondelete="SET NULL"), nullable=True, index=True)
    
    # item_code - VARCHAR(100), optional.
    # Item/article code for this line.
    item_code = Column(String(100), nullable=True)
    # description - TEXT, required.
    # Free-text description.
    description = Column(Text, nullable=False)
    # default_quantity - NUMERIC(12,2), required, default 1.0.
    # Quantity pre-filled when the template is used.
    default_quantity = Column(Numeric(12, 2), nullable=False, default=1.0)
    # unit - VARCHAR(50), optional, default PCS.
    # Unit of measure, e.g. PCS, KG.
    unit = Column(String(50), default="PCS")
    
    # unit_price - NUMERIC(14,2), optional.
    # Price pre-filled when the template is used.
    unit_price = Column(Numeric(14, 2), nullable=True)
    # currency - VARCHAR(10), optional, default USD.
    # Currency code of the amounts on this row (e.g. USD, SCR).
    currency = Column(String(10), default="USD")
    
    # sort_order - INTEGER, optional, default 0.
    # Display order; lower numbers appear first.
    sort_order = Column(Integer, default=0)
    # notes - TEXT, optional.
    # Free-text remarks.
    notes = Column(Text, nullable=True)

    # Relationships
    template = relationship("OrderTemplate", back_populates="items")
    product = relationship("Product", foreign_keys=[product_id], lazy="joined")

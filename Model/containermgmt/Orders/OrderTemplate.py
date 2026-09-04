from sqlalchemy import Column, Integer, String, Text, ForeignKey, JSON, Numeric, Boolean
from sqlalchemy.orm import relationship
from ...db import Base
from ...mixins import AuditMixin, OrgMixin

class OrderTemplate(OrgMixin, AuditMixin, Base):
    __tablename__ = "order_templates"
    __table_args__ = {'schema': 'containermgmt'}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    tags = Column(JSON, nullable=True)  # List of string tags, e.g. ["Hardware", "Monthly", "Urgent"]
    
    supplier_id = Column(Integer, ForeignKey("containermgmt.supplier.supplier_id", ondelete="SET NULL"), nullable=True)
    company = Column(String(255), nullable=True)  # Fallback supplier company name
    freight_type = Column(String(50), default="Sea Freight")
    notes = Column(Text, nullable=True)
    
    # Visibility: 'org' (visible to entire org) or 'private' (visible only to created_by)
    visibility = Column(String(20), default="org", nullable=False)

    # Relationships
    supplier_rel = relationship("Supplier", foreign_keys=[supplier_id], lazy="joined")
    items = relationship(
        "OrderTemplateItem",
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="OrderTemplateItem.sort_order"
    )


class OrderTemplateItem(AuditMixin, Base):
    __tablename__ = "order_template_items"
    __table_args__ = {'schema': 'containermgmt'}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    template_id = Column(Integer, ForeignKey("containermgmt.order_templates.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("containermgmt.products.id", ondelete="SET NULL"), nullable=True, index=True)
    
    item_code = Column(String(100), nullable=True)
    description = Column(Text, nullable=False)
    default_quantity = Column(Numeric(12, 2), nullable=False, default=1.0)
    unit = Column(String(50), default="PCS")
    
    unit_price = Column(Numeric(14, 2), nullable=True)
    currency = Column(String(10), default="USD")
    
    sort_order = Column(Integer, default=0)
    notes = Column(Text, nullable=True)

    # Relationships
    template = relationship("OrderTemplate", back_populates="items")
    product = relationship("Product", foreign_keys=[product_id], lazy="joined")

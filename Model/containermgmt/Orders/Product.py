from sqlalchemy import (
    Column, Integer, String, Text, ForeignKey,
    Numeric, Boolean, JSON
)
from sqlalchemy.orm import relationship
from ...db import Base
from ...mixins import AuditMixin


class ProductCategory(AuditMixin, Base):
    __tablename__ = "product_categories"
    __table_args__ = {'schema': 'containermgmt'}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    org_id = Column(Integer, ForeignKey("usercredentials.organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)

    # Hierarchy
    parent_id = Column(Integer, ForeignKey("containermgmt.product_categories.id", ondelete="SET NULL"), nullable=True, index=True)
    is_subcategory = Column(Boolean, default=False)

    # Media
    images = Column(JSON, nullable=True)       # [{id, file_name, file_url, file_type}]
    attachments = Column(JSON, nullable=True)  # [{id, file_name, file_url, file_type}]

    # Relationships
    parent = relationship("ProductCategory", remote_side="ProductCategory.id", foreign_keys="ProductCategory.parent_id", backref="children")
    products = relationship("Product", back_populates="category")


class Product(AuditMixin, Base):
    __tablename__ = "products"
    __table_args__ = {'schema': 'containermgmt'}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    org_id = Column(Integer, ForeignKey("usercredentials.organisations.id", ondelete="CASCADE"), nullable=False, index=True)

    # ── Core Identity ──────────────────────────────────────────────────────────
    code = Column(String(100), nullable=True, index=True)   # Internal org code e.g. ITEM-CT-001
    sku = Column(String(100), nullable=False, index=True)    # External/supplier SKU
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    description_quick = Column(String(500), nullable=True)  # Short one-liner for lists

    # status: 'active' | 'inactive'  (active by default)
    status = Column(String(20), default="active", nullable=False)

    # ── Classification ─────────────────────────────────────────────────────────
    category_id = Column(Integer, ForeignKey("containermgmt.product_categories.id", ondelete="SET NULL"), nullable=True, index=True)
    brand = Column(String(100), nullable=True)
    model_number = Column(String(100), nullable=True)
    series = Column(String(100), nullable=True)
    country_of_origin = Column(String(100), nullable=True)    # ISO code or Country Name e.g. 'CN', 'China'
    barcode = Column(String(100), nullable=True)
    hs_code = Column(String(20), nullable=True)
    duty_rate = Column(Numeric(5, 2), nullable=True)         # Import duty %
    tags = Column(JSON, nullable=True)                       # ["ceramic", "outdoor"]

    # ── Unit of Measure ────────────────────────────────────────────────────────
    unit = Column(String(50), default="PCS")

    # ── Physical Dimensions ────────────────────────────────────────────────────
    length = Column(Numeric(10, 4), nullable=True)
    width = Column(Numeric(10, 4), nullable=True)
    height = Column(Numeric(10, 4), nullable=True)
    weight_per_unit = Column(Numeric(10, 4), nullable=True)
    dimension_unit = Column(String(10), nullable=True, default="mm")  # mm / cm / in
    weight_unit = Column(String(10), nullable=True, default="kg")      # kg / g / lbs
    units_per_box = Column(Numeric(12, 4), nullable=True)
    box_weight = Column(Numeric(10, 4), nullable=True)

    # ── Pricing & Costing (role-gated in API) ──────────────────────────────────
    unit_cost = Column(Numeric(14, 2), nullable=True)
    currency = Column(String(10), default="USD")

    # ── Stock Thresholds ───────────────────────────────────────────────────────
    current_stock = Column(Numeric(12, 2), default=0.0)
    min_stock_quantity = Column(Numeric(12, 2), default=0.0)     # Reorder alert
    max_stock_quantity = Column(Numeric(12, 2), nullable=True)   # Over-stock cap
    order_threshold_qty = Column(Numeric(12, 2), nullable=True)  # Trigger for reorder
    threshold_qty = Column(Numeric(12, 2), nullable=True)         # Safety stock cushion
    min_quantity_order = Column(Numeric(12, 2), nullable=True)   # Min order qty (own MOQ)
    lead_time_days = Column(Integer, nullable=True)

    # ── Supplier ───────────────────────────────────────────────────────────────
    default_supplier_id = Column(Integer, ForeignKey("containermgmt.supplier.supplier_id", ondelete="SET NULL"), nullable=True, index=True)

    # ── Media & Documentation ──────────────────────────────────────────────────
    images = Column(JSON, nullable=True)      # [{id, file_name, file_url, file_type, file_size}]
    videos = Column(JSON, nullable=True)      # [{id, file_name, file_url, file_type, file_size, thumbnail_url}]
    attachment = Column(JSON, nullable=True)  # [{id, file_name, file_url, file_type, file_size}]

    # ── Flags ──────────────────────────────────────────────────────────────────
    is_consumable = Column(Boolean, default=False)
    is_hazardous = Column(Boolean, default=False)
    is_perishable = Column(Boolean, default=False)
    expiry_days = Column(Integer, nullable=True)
    is_returnable = Column(Boolean, default=True)
    warranty_days = Column(Integer, nullable=True)

    # ── Relationships ──────────────────────────────────────────────────────────
    category = relationship("ProductCategory", back_populates="products")
    supplier = relationship("Supplier")
    po_items = relationship("POItem", back_populates="product")

    # Links where this product is the parent (has variants/related/parts below it)
    parent_links = relationship(
        "ProductLink",
        foreign_keys="ProductLink.parent_product_id",
        back_populates="parent_product",
        lazy="dynamic"
    )
    # Links where this product is the child (belongs to a parent)
    child_links = relationship(
        "ProductLink",
        foreign_keys="ProductLink.child_product_id",
        back_populates="child_product",
        lazy="dynamic"
    )


class ProductLink(AuditMixin, Base):
    """
    Unified relationship table for product variants, related items, and BOM parts.

    One row per (parent, child) pair within an org. Multiple flags can be true
    simultaneously — e.g. is_variant=True AND is_related=True means the child
    is both a variant of and an alternative for the parent.

    Flags:
        is_variant  — child is a size/color/finish variant of the parent
        is_related  — child is a related/alternative/accessory for the parent
        is_part     — child is a BOM component of the parent (qty = how many per unit)
    """
    __tablename__ = "product_links"
    __table_args__ = {'schema': 'containermgmt'}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    org_id = Column(Integer, ForeignKey("usercredentials.organisations.id", ondelete="CASCADE"), nullable=False, index=True)

    parent_product_id = Column(Integer, ForeignKey("containermgmt.products.id", ondelete="CASCADE"), nullable=False, index=True)
    child_product_id = Column(Integer, ForeignKey("containermgmt.products.id", ondelete="CASCADE"), nullable=False, index=True)

    is_variant = Column(Boolean, default=False, nullable=False)
    is_related = Column(Boolean, default=False, nullable=False)
    is_part = Column(Boolean, default=False, nullable=False)

    qty = Column(Numeric(12, 4), nullable=True)   # Qty of child per parent unit (for is_part)
    sort_order = Column(Integer, default=0)
    notes = Column(Text, nullable=True)

    # Relationships
    parent_product = relationship("Product", foreign_keys=[parent_product_id], back_populates="parent_links")
    child_product = relationship("Product", foreign_keys=[child_product_id], back_populates="child_links")

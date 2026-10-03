from sqlalchemy import (
    Column, Integer, String, Text, ForeignKey,
    Numeric, Boolean, JSON, UniqueConstraint
)
from sqlalchemy.orm import relationship
from ...db import Base
from ...mixins import AuditMixin, OrgMixin


class ProductCategory(OrgMixin, AuditMixin, Base):
    __tablename__ = "product_categories"
    __table_args__ = {'schema': 'containermgmt'}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    is_shared = Column(Boolean, default=False, nullable=False, index=True)

    # Hierarchy
    parent_id = Column(Integer, ForeignKey("containermgmt.product_categories.id", ondelete="SET NULL"), nullable=True, index=True)
    is_subcategory = Column(Boolean, default=False)

    # Media
    images = Column(JSON, nullable=True)       # [{id, file_name, file_url, file_type}]
    attachments = Column(JSON, nullable=True)  # [{id, file_name, file_url, file_type}]

    # Relationships
    parent = relationship("ProductCategory", remote_side="ProductCategory.id", foreign_keys="ProductCategory.parent_id", backref="children")
    products = relationship("Product", back_populates="category")


class Product(OrgMixin, AuditMixin, Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint('id', 'org_id', name='uq_product_id_org'),
        {'schema': 'containermgmt'},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    # ── Core Identity ──────────────────────────────────────────────────────────
    code = Column(String(100), nullable=True, index=True)   # Internal org code e.g. ITEM-CT-001
    sku = Column(String(100), nullable=False, index=True)    # External/supplier SKU
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    description_quick = Column(String(500), nullable=True)  # Short one-liner for lists
    is_shared = Column(Boolean, default=False, nullable=False, index=True)

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

    # ── Multi-Tier Packaging Specs ─────────────────────────────────────────────
    # Retail / Primary Packaging
    retail_packaging_type = Column(String(100), nullable=True)
    gross_weight_per_unit = Column(Numeric(10, 4), nullable=True)

    # Wholesale / Inner Packaging
    wholesale_packaging_type = Column(String(100), nullable=True)
    units_per_inner = Column(Numeric(12, 4), nullable=True)
    inner_length = Column(Numeric(10, 4), nullable=True)
    inner_width = Column(Numeric(10, 4), nullable=True)
    inner_height = Column(Numeric(10, 4), nullable=True)
    inner_weight = Column(Numeric(10, 4), nullable=True)

    # Import / Master Shipping Packaging
    import_packaging_type = Column(String(100), nullable=True)
    master_length = Column(Numeric(10, 4), nullable=True)
    master_width = Column(Numeric(10, 4), nullable=True)
    master_height = Column(Numeric(10, 4), nullable=True)
    master_tare_weight = Column(Numeric(10, 4), nullable=True)

    # Palletization & Container Loading (auto-estimated & user-editable)
    pallet_type = Column(String(100), nullable=True)
    cartons_per_layer = Column(Integer, nullable=True)
    layers_per_pallet = Column(Integer, nullable=True)
    total_cartons_per_pallet = Column(Integer, nullable=True)
    max_stacking_layers = Column(Integer, nullable=True)
    est_qty_20ft = Column(Numeric(12, 2), nullable=True)
    est_qty_40hc = Column(Numeric(12, 2), nullable=True)

    # Warehouse & Bin Coordinates (WMS Preparation)
    warehouse_location = Column(String(150), nullable=True)
    default_bin = Column(String(100), nullable=True)

    # Extensible Packaging JSON
    packaging_specs = Column(JSON, nullable=True)

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
    product_suppliers = relationship("ProductSupplier", back_populates="product", cascade="all, delete-orphan", lazy="joined")
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


class ProductLink(OrgMixin, AuditMixin, Base):
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


class ProductSupplier(OrgMixin, AuditMixin, Base):
    """
    Mapping table between a Product and its authorized Suppliers/Vendors/Factories.
    Supports multiple vendors per product, vendor-specific factory codes (SKU/Article No.),
    vendor unit pricing, MOQ, lead times, and designating one as the default/preferred vendor.
    """
    __tablename__ = "product_suppliers"
    __table_args__ = {'schema': 'containermgmt'}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey("containermgmt.products.id", ondelete="CASCADE"), nullable=False, index=True)
    supplier_id = Column(Integer, ForeignKey("containermgmt.supplier.supplier_id", ondelete="CASCADE"), nullable=False, index=True)

    factory_code = Column(String(100), nullable=True, index=True)          # Vendor / Factory article number or code
    vendor_product_name = Column(String(255), nullable=True)               # Vendor's catalog name or description
    unit_cost = Column(Numeric(14, 2), nullable=True)                      # Quoted price from this vendor
    currency = Column(String(10), default="USD", nullable=False)
    min_order_qty = Column(Numeric(12, 2), nullable=True)                  # Vendor MOQ
    lead_time_days = Column(Integer, nullable=True)                        # Vendor manufacturing/delivery lead time
    is_default = Column(Boolean, default=False, nullable=False)            # Preferred default supplier flag
    notes = Column(Text, nullable=True)

    # Relationships
    product = relationship("Product", back_populates="product_suppliers")
    supplier = relationship("Supplier", lazy="joined")


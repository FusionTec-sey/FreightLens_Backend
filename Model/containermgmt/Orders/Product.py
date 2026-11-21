from sqlalchemy import (
    Column, Integer, String, Text, ForeignKey,
    Numeric, Boolean, JSON
)
from sqlalchemy.orm import relationship
from ...db import Base
from ...mixins import AuditMixin, OrgMixin


# TABLE: Product category tree.
class ProductCategory(OrgMixin, AuditMixin, Base):
    __tablename__ = "product_categories"
    __table_args__ = {'schema': 'containermgmt'}

    # id - INTEGER, primary key.
    # Unique row number.
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    # name - VARCHAR(100), required.
    # Category name.
    name = Column(String(100), nullable=False)
    # description - TEXT, optional.
    # Free-text description.
    description = Column(Text, nullable=True)
    # is_shared - BOOLEAN, required, default False.
    # True = visible to every company, not only the owning one.
    is_shared = Column(Boolean, default=False, nullable=False, index=True)

    # Hierarchy
    # parent_id - INTEGER, foreign key -> containermgmt.product_categories.id, optional.
    # Parent category (NULL = top level).
    parent_id = Column(Integer, ForeignKey("containermgmt.product_categories.id", ondelete="SET NULL"), nullable=True, index=True)
    # is_subcategory - BOOLEAN, optional, default False.
    # True if it sits under another category.
    is_subcategory = Column(Boolean, default=False)

    # Media
    # images - JSON, optional.
    # Attached images (JSON list of file name/url/type).
    images = Column(JSON, nullable=True)       # [{id, file_name, file_url, file_type}]
    # attachments - JSON, optional.
    # Attached files (JSON list).
    attachments = Column(JSON, nullable=True)  # [{id, file_name, file_url, file_type}]

    # Relationships
    parent = relationship("ProductCategory", remote_side="ProductCategory.id", foreign_keys="ProductCategory.parent_id", backref="children")
    products = relationship("Product", back_populates="category")


# TABLE: The company's product catalogue (items bought/stocked).
class Product(OrgMixin, AuditMixin, Base):
    __tablename__ = "products"
    __table_args__ = {'schema': 'containermgmt'}

    # id - INTEGER, primary key.
    # Unique row number.
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    # ── Core Identity ──────────────────────────────────────────────────────────
    # code - VARCHAR(100), optional.
    # Internal company code, e.g. ITEM-CT-001.
    code = Column(String(100), nullable=True, index=True)   # Internal org code e.g. ITEM-CT-001
    # sku - VARCHAR(100), required.
    # External/supplier SKU.
    sku = Column(String(100), nullable=False, index=True)    # External/supplier SKU
    # name - VARCHAR(255), required.
    # Product name.
    name = Column(String(255), nullable=False)
    # description - TEXT, optional.
    # Free-text description.
    description = Column(Text, nullable=True)
    # description_quick - VARCHAR(500), optional.
    # Short one-line description for lists.
    description_quick = Column(String(500), nullable=True)  # Short one-liner for lists
    # Where this product was copied from, when it was adopted from the group
    # dictionary. Provenance, not a dependency: SET NULL, so deleting a
    # definition never breaks a company's catalogue. (It replaces an is_shared
    # flag that nothing ever read -- the same trap product_categories.is_shared
    # set, which kept a catalogue bug invisible for months.)
    # definition_id - INTEGER, foreign key -> containermgmt.product_definitions.id, optional.
    # Group master product it was copied from (provenance only).
    definition_id = Column(
        Integer,
        ForeignKey("containermgmt.product_definitions.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    # status: 'active' | 'inactive'  (active by default)
    # status - VARCHAR(20), required, default active.
    # 'active' or 'inactive'.
    status = Column(String(20), default="active", nullable=False)

    # ── Classification ─────────────────────────────────────────────────────────
    # category_id - INTEGER, foreign key -> containermgmt.product_categories.id, optional.
    # Product category.
    category_id = Column(Integer, ForeignKey("containermgmt.product_categories.id", ondelete="SET NULL"), nullable=True, index=True)
    # brand - VARCHAR(100), optional.
    # Brand.
    brand = Column(String(100), nullable=True)
    # model_number - VARCHAR(100), optional.
    # Model number.
    model_number = Column(String(100), nullable=True)
    # series - VARCHAR(100), optional.
    # Product series.
    series = Column(String(100), nullable=True)
    # country_of_origin - VARCHAR(100), optional.
    # Country of manufacture.
    country_of_origin = Column(String(100), nullable=True)    # ISO code or Country Name e.g. 'CN', 'China'
    # barcode - VARCHAR(100), optional.
    # Barcode/EAN.
    barcode = Column(String(100), nullable=True)
    # hs_code - VARCHAR(20), optional.
    # Customs tariff (HS) code.
    hs_code = Column(String(20), nullable=True)
    # duty_rate - NUMERIC(5,2), optional.
    # Import duty %.
    duty_rate = Column(Numeric(5, 2), nullable=True)         # Import duty %
    # tags - JSON, optional.
    # Free-form labels (JSON list) for searching and grouping.
    tags = Column(JSON, nullable=True)                       # ["ceramic", "outdoor"]

    # ── Unit of Measure ────────────────────────────────────────────────────────
    # unit - VARCHAR(50), optional, default PCS.
    # Unit of measure, e.g. PCS, KG.
    unit = Column(String(50), default="PCS")

    # ── Physical Dimensions ────────────────────────────────────────────────────
    # length - NUMERIC(10,4), optional.
    # Product length.
    length = Column(Numeric(10, 4), nullable=True)
    # width - NUMERIC(10,4), optional.
    # Product width.
    width = Column(Numeric(10, 4), nullable=True)
    # height - NUMERIC(10,4), optional.
    # Product height.
    height = Column(Numeric(10, 4), nullable=True)
    # weight_per_unit - NUMERIC(10,4), optional.
    # Weight of one unit.
    weight_per_unit = Column(Numeric(10, 4), nullable=True)
    # dimension_unit - VARCHAR(10), optional, default mm.
    # Unit for dimensions: mm, cm or in.
    dimension_unit = Column(String(10), nullable=True, default="mm")  # mm / cm / in
    # weight_unit - VARCHAR(10), optional, default kg.
    # Unit for weight: kg, g or lbs.
    weight_unit = Column(String(10), nullable=True, default="kg")      # kg / g / lbs
    # units_per_box - NUMERIC(12,4), optional.
    # Units in one box.
    units_per_box = Column(Numeric(12, 4), nullable=True)
    # box_weight - NUMERIC(10,4), optional.
    # Weight of one full box.
    box_weight = Column(Numeric(10, 4), nullable=True)

    # ── Multi-Tier Packaging Specs ─────────────────────────────────────────────
    # Retail / Primary Packaging
    # retail_packaging_type - VARCHAR(100), optional.
    # Retail (primary) packaging type.
    retail_packaging_type = Column(String(100), nullable=True)
    # gross_weight_per_unit - NUMERIC(10,4), optional.
    # Weight of one unit including retail packaging.
    gross_weight_per_unit = Column(Numeric(10, 4), nullable=True)

    # Wholesale / Inner Packaging
    # wholesale_packaging_type - VARCHAR(100), optional.
    # Wholesale (inner) packaging type.
    wholesale_packaging_type = Column(String(100), nullable=True)
    # units_per_inner - NUMERIC(12,4), optional.
    # Units per inner pack.
    units_per_inner = Column(Numeric(12, 4), nullable=True)
    # inner_length - NUMERIC(10,4), optional.
    # Inner pack length.
    inner_length = Column(Numeric(10, 4), nullable=True)
    # inner_width - NUMERIC(10,4), optional.
    # Inner pack width.
    inner_width = Column(Numeric(10, 4), nullable=True)
    # inner_height - NUMERIC(10,4), optional.
    # Inner pack height.
    inner_height = Column(Numeric(10, 4), nullable=True)
    # inner_weight - NUMERIC(10,4), optional.
    # Inner pack weight.
    inner_weight = Column(Numeric(10, 4), nullable=True)

    # Import / Master Shipping Packaging
    # import_packaging_type - VARCHAR(100), optional.
    # Master shipping carton type.
    import_packaging_type = Column(String(100), nullable=True)
    # master_length - NUMERIC(10,4), optional.
    # Master carton length.
    master_length = Column(Numeric(10, 4), nullable=True)
    # master_width - NUMERIC(10,4), optional.
    # Master carton width.
    master_width = Column(Numeric(10, 4), nullable=True)
    # master_height - NUMERIC(10,4), optional.
    # Master carton height.
    master_height = Column(Numeric(10, 4), nullable=True)
    # master_tare_weight - NUMERIC(10,4), optional.
    # Empty weight of the master carton.
    master_tare_weight = Column(Numeric(10, 4), nullable=True)

    # Palletization & Container Loading (auto-estimated & user-editable)
    # pallet_type - VARCHAR(100), optional.
    # Pallet type.
    pallet_type = Column(String(100), nullable=True)
    # cartons_per_layer - INTEGER, optional.
    # Cartons in one pallet layer.
    cartons_per_layer = Column(Integer, nullable=True)
    # layers_per_pallet - INTEGER, optional.
    # Layers on a pallet.
    layers_per_pallet = Column(Integer, nullable=True)
    # total_cartons_per_pallet - INTEGER, optional.
    # Cartons on a full pallet.
    total_cartons_per_pallet = Column(Integer, nullable=True)
    # max_stacking_layers - INTEGER, optional.
    # Maximum layers that can be stacked.
    max_stacking_layers = Column(Integer, nullable=True)
    # est_qty_20ft - NUMERIC(12,2), optional.
    # Estimated units fitting in a 20ft container.
    est_qty_20ft = Column(Numeric(12, 2), nullable=True)
    # est_qty_40hc - NUMERIC(12,2), optional.
    # Estimated units fitting in a 40ft high-cube container.
    est_qty_40hc = Column(Numeric(12, 2), nullable=True)

    # Warehouse & Bin Coordinates (WMS Preparation)
    # warehouse_location - VARCHAR(150), optional.
    # Default warehouse location.
    warehouse_location = Column(String(150), nullable=True)
    # default_bin - VARCHAR(100), optional.
    # Default bin/shelf.
    default_bin = Column(String(100), nullable=True)

    # Extensible Packaging JSON
    # packaging_specs - JSON, optional.
    # Extra packaging details (JSON).
    packaging_specs = Column(JSON, nullable=True)

    # ── Pricing & Costing (role-gated in API) ──────────────────────────────────
    # unit_cost - NUMERIC(14,2), optional.
    # Standard cost per unit (role-gated in the API).
    unit_cost = Column(Numeric(14, 2), nullable=True)
    # currency - VARCHAR(10), optional, default USD.
    # Currency of unit_cost.
    currency = Column(String(10), default="USD")

    # ── Stock Thresholds ───────────────────────────────────────────────────────
    # current_stock - NUMERIC(12,2), optional, default 0.0.
    # Quantity currently in stock.
    current_stock = Column(Numeric(12, 2), default=0.0)
    # min_stock_quantity - NUMERIC(12,2), optional, default 0.0.
    # Reorder alert level.
    min_stock_quantity = Column(Numeric(12, 2), default=0.0)     # Reorder alert
    # max_stock_quantity - NUMERIC(12,2), optional.
    # Over-stock cap.
    max_stock_quantity = Column(Numeric(12, 2), nullable=True)   # Over-stock cap
    # order_threshold_qty - NUMERIC(12,2), optional.
    # Stock level that triggers a reorder.
    order_threshold_qty = Column(Numeric(12, 2), nullable=True)  # Trigger for reorder
    # threshold_qty - NUMERIC(12,2), optional.
    # Safety-stock cushion.
    threshold_qty = Column(Numeric(12, 2), nullable=True)         # Safety stock cushion
    # min_quantity_order - NUMERIC(12,2), optional.
    # Our own minimum order quantity.
    min_quantity_order = Column(Numeric(12, 2), nullable=True)   # Min order qty (own MOQ)
    # lead_time_days - INTEGER, optional.
    # Typical days from order to delivery.
    lead_time_days = Column(Integer, nullable=True)

    # ── Supplier ───────────────────────────────────────────────────────────────
    # default_supplier_id - INTEGER, foreign key -> containermgmt.supplier.supplier_id, optional.
    # Preferred vendor.
    default_supplier_id = Column(Integer, ForeignKey("containermgmt.supplier.supplier_id", ondelete="SET NULL"), nullable=True, index=True)

    # ── Media & Documentation ──────────────────────────────────────────────────
    # images - JSON, optional.
    # Attached images (JSON list of file name/url/type).
    images = Column(JSON, nullable=True)      # [{id, file_name, file_url, file_type, file_size}]
    # videos - JSON, optional.
    # Attached videos (JSON list).
    videos = Column(JSON, nullable=True)      # [{id, file_name, file_url, file_type, file_size, thumbnail_url}]
    # attachment - JSON, optional.
    # Attached files (JSON list).
    attachment = Column(JSON, nullable=True)  # [{id, file_name, file_url, file_type, file_size}]

    # ── Flags ──────────────────────────────────────────────────────────────────
    # is_consumable - BOOLEAN, optional, default False.
    # True if used up in operation.
    is_consumable = Column(Boolean, default=False)
    # is_hazardous - BOOLEAN, optional, default False.
    # True for dangerous goods.
    is_hazardous = Column(Boolean, default=False)
    # is_perishable - BOOLEAN, optional, default False.
    # True if it expires.
    is_perishable = Column(Boolean, default=False)
    # expiry_days - INTEGER, optional.
    # Shelf life in days.
    expiry_days = Column(Integer, nullable=True)
    # is_returnable - BOOLEAN, optional, default True.
    # True if it can be returned to the vendor.
    is_returnable = Column(Boolean, default=True)
    # warranty_days - INTEGER, optional.
    # Warranty period in days.
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


# TABLE: Relationships between products: variants, related items and BOM parts.
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

    # id - INTEGER, primary key.
    # Unique row number.
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    # parent_product_id - INTEGER, foreign key -> containermgmt.products.id, required.
    # The main product.
    parent_product_id = Column(Integer, ForeignKey("containermgmt.products.id", ondelete="CASCADE"), nullable=False, index=True)
    # child_product_id - INTEGER, foreign key -> containermgmt.products.id, required.
    # The linked product (variant, related item or part).
    child_product_id = Column(Integer, ForeignKey("containermgmt.products.id", ondelete="CASCADE"), nullable=False, index=True)

    # is_variant - BOOLEAN, required, default False.
    # Child is a size/colour/finish variant of the parent.
    is_variant = Column(Boolean, default=False, nullable=False)
    # is_related - BOOLEAN, required, default False.
    # Child is a related item/alternative/accessory.
    is_related = Column(Boolean, default=False, nullable=False)
    # is_part - BOOLEAN, required, default False.
    # Child is a bill-of-materials component of the parent.
    is_part = Column(Boolean, default=False, nullable=False)

    # qty - NUMERIC(12,4), optional.
    # Quantity of the child per parent unit (for parts).
    qty = Column(Numeric(12, 4), nullable=True)   # Qty of child per parent unit (for is_part)
    # sort_order - INTEGER, optional, default 0.
    # Display order; lower numbers appear first.
    sort_order = Column(Integer, default=0)
    # notes - TEXT, optional.
    # Free-text remarks.
    notes = Column(Text, nullable=True)

    # Relationships
    parent_product = relationship("Product", foreign_keys=[parent_product_id], back_populates="parent_links")
    child_product = relationship("Product", foreign_keys=[child_product_id], back_populates="child_links")


# TABLE: Which vendors can supply a product, with their code, price, MOQ and lead time.
class ProductSupplier(OrgMixin, AuditMixin, Base):
    """
    Mapping table between a Product and its authorized Suppliers/Vendors/Factories.
    Supports multiple vendors per product, vendor-specific factory codes (SKU/Article No.),
    vendor unit pricing, MOQ, lead times, and designating one as the default/preferred vendor.
    """
    __tablename__ = "product_suppliers"
    __table_args__ = {'schema': 'containermgmt'}

    # id - INTEGER, primary key.
    # Unique row number.
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    # product_id - INTEGER, foreign key -> containermgmt.products.id, required.
    # Product being supplied.
    product_id = Column(Integer, ForeignKey("containermgmt.products.id", ondelete="CASCADE"), nullable=False, index=True)
    # supplier_id - INTEGER, foreign key -> containermgmt.supplier.supplier_id, required.
    # Vendor who can supply it.
    supplier_id = Column(Integer, ForeignKey("containermgmt.supplier.supplier_id", ondelete="CASCADE"), nullable=False, index=True)

    # factory_code - VARCHAR(100), optional.
    # Vendor's own article/factory code.
    factory_code = Column(String(100), nullable=True, index=True)          # Vendor / Factory article number or code
    # vendor_product_name - VARCHAR(255), optional.
    # Vendor's catalogue name.
    vendor_product_name = Column(String(255), nullable=True)               # Vendor's catalog name or description
    # unit_cost - NUMERIC(14,2), optional.
    # Price quoted by this vendor.
    unit_cost = Column(Numeric(14, 2), nullable=True)                      # Quoted price from this vendor
    # currency - VARCHAR(10), required, default USD.
    # Currency code of the amounts on this row (e.g. USD, SCR).
    currency = Column(String(10), default="USD", nullable=False)
    # min_order_qty - NUMERIC(12,2), optional.
    # Vendor minimum order quantity.
    min_order_qty = Column(Numeric(12, 2), nullable=True)                  # Vendor MOQ
    # lead_time_days - INTEGER, optional.
    # Vendor lead time in days.
    lead_time_days = Column(Integer, nullable=True)                        # Vendor manufacturing/delivery lead time
    # is_default - BOOLEAN, required, default False.
    # True = preferred vendor for the product.
    is_default = Column(Boolean, default=False, nullable=False)            # Preferred default supplier flag
    # notes - TEXT, optional.
    # Free-text remarks.
    notes = Column(Text, nullable=True)

    # Relationships
    product = relationship("Product", back_populates="product_suppliers")
    supplier = relationship("Supplier", lazy="joined")


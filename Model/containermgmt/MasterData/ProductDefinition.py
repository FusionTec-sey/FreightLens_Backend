from sqlalchemy import Column, Integer, String, Text, Numeric, Boolean, ForeignKey, Index

from ...db import Base
from ...mixins import AuditMixin


# TABLE: Group-wide master product (no stock/cost/supplier). A company adopts it by copying it into
#        its own product.
class ProductDefinition(AuditMixin, Base):
    """What is true about a product for every company in the group.

    Deliberately holds no company data: no stock, no cost, no internal code, no
    supplier. Those differ per company and stay on that company's own product
    row, which is why a product is copied from here rather than shared from it.

    A company adopts a definition, which copies these fields into a product of
    its own and records `products.definition_id` back to this row. The link is
    what makes group-wide reporting possible without the companies sharing a
    record they would otherwise fight over -- and it is why deleting a
    definition cannot break anything: the copy already holds everything the
    company needs.
    """
    __tablename__ = "product_definitions"
    __table_args__ = (
        Index("ix_product_definitions_sku_unique", "sku_key", unique=True),
        {"schema": "containermgmt"},
    )

    # id - INTEGER, primary key.
    # Unique row number.
    id = Column(Integer, primary_key=True, autoincrement=True)

    # SKU is the natural key: across 5,790 products it was unique and never
    # blank. sku_key is its normalised form, so case and spacing cannot produce
    # the duplicates the vendor master accumulated.
    # sku - VARCHAR(100), required.
    # Supplier/standard SKU as entered.
    sku = Column(String(100), nullable=False)
    # sku_key - VARCHAR(100), required.
    # Normalised SKU (case/spacing removed); unique, prevents duplicates.
    sku_key = Column(String(100), nullable=False)

    # name - VARCHAR(255), required.
    # Product name.
    name = Column(String(255), nullable=False)
    # description - TEXT, optional.
    # Free-text description.
    description = Column(Text, nullable=True)
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
    country_of_origin = Column(String(100), nullable=True)
    # barcode - VARCHAR(100), optional.
    # Barcode/EAN.
    barcode = Column(String(100), nullable=True)
    # hs_code - VARCHAR(20), optional.
    # Customs tariff (HS) code.
    hs_code = Column(String(20), nullable=True)
    # unit - VARCHAR(50), optional, default PCS.
    # Unit of measure, e.g. PCS, KG.
    unit = Column(String(50), nullable=True, default="PCS")

    # length - NUMERIC(10,4), optional.
    # Length.
    length = Column(Numeric(10, 4), nullable=True)
    # width - NUMERIC(10,4), optional.
    # Width.
    width = Column(Numeric(10, 4), nullable=True)
    # height - NUMERIC(10,4), optional.
    # Height.
    height = Column(Numeric(10, 4), nullable=True)
    # weight_per_unit - NUMERIC(10,4), optional.
    # Weight of one unit.
    weight_per_unit = Column(Numeric(10, 4), nullable=True)
    # dimension_unit - VARCHAR(10), optional.
    # Unit for length/width/height (mm, cm, in).
    dimension_unit = Column(String(10), nullable=True)
    # weight_unit - VARCHAR(10), optional.
    # Unit for weight (kg, g, lbs).
    weight_unit = Column(String(10), nullable=True)

    # A hint, not a rule: a company on its own catalogue has to map it.
    # suggested_category_id - INTEGER, foreign key -> containermgmt.product_categories.id, optional.
    # Hint for category when adopted (a company may map differently).
    suggested_category_id = Column(
        Integer,
        ForeignKey("containermgmt.product_categories.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Who first published it. Provenance only -- it grants no ownership, since
    # every company reads every definition.
    # source_org_id - INTEGER, optional.
    # Company that first published it (provenance only, no ownership).
    source_org_id = Column(Integer, nullable=True)
    # is_active - BOOLEAN, required, default True.
    # False hides the record from use without deleting it.
    is_active = Column(Boolean, default=True, nullable=False)
